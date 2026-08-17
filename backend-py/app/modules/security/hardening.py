"""Security Hardening (Batch 30, additive).

Adds the missing Batch 30 enterprise security features on top of
``security/module.py`` and ``foundation/security.py``:

  - MFA: RFC-6238 TOTP (no external dependency — HMAC-SHA1 via stdlib)
  - Secret Vault: encrypted secret storage with a Fernet-compatible key derived
    from the configured secret (cryptography is optional; falls back to the
    existing AES implementation when unavailable).
  - CSRF token issuance/validation
  - SSRF guard: URL allow/deny validation before outbound fetches
  - Webhook signature verification (HMAC-SHA256)

Everything here is additive; existing security modules are left untouched.
"""
import base64
import hashlib
import hmac
import os
import re
import struct
import time
import urllib.parse

from ...config import settings
from ...foundation.event_bus import event_bus
from ...foundation.logger import logger
from ...foundation.security import security

try:
    from cryptography.fernet import Fernet  # noqa: F401
    _HAVE_FERNET = True
except Exception:  # noqa: BLE001 - optional dependency
    _HAVE_FERNET = False


class TOTP:
    """RFC-6238 Time-based One-Time Password (HMAC-SHA1, 6 digits)."""

    def __init__(self, secret=None, digits=6, step=30):
        if secret is None:
            secret = os.environ.get("TOTP_SECRET") or security.random_bytes(32)
        self.secret = str(secret)
        self.digits = int(digits)
        self.step = int(step)

    def _key(self):
        # Accept base32 secrets (standard) or raw hex.
        key = self.secret.strip()
        if re.fullmatch(r"[A-Z2-7=]+", key.upper()):
            try:
                return base64.b32decode(key.upper().replace("=", "") + "=" * ((8 - len(key) % 8) % 8))
            except Exception:  # noqa: BLE001
                pass
        try:
            return bytes.fromhex(key)
        except (ValueError, TypeError):
            return key.encode()

    def code_at(self, counter):
        msg = struct.pack(">Q", counter)
        digest = hmac.new(self._key(), msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return f"{binary % (10 ** self.digits):0{self.digits}d}"

    def now(self):
        return self.code_at(int(time.time() // self.step))

    def verify(self, code, window=1):
        if not code:
            return False
        counter = int(time.time() // self.step)
        for delta in range(-window, window + 1):
            if hmac.compare_digest(str(code).strip(), self.code_at(counter + delta)):
                return True
        return False

    def provisioning_uri(self, account):
        issuer = urllib.parse.quote("QuantOS AI")
        secret_b32 = base64.b32encode(self._key()).decode().rstrip("=")
        return f"otpauth://totp/{urllib.parse.quote(account)}?secret={secret_b32}&issuer={issuer}"


class SecretVault:
    """Encrypted storage of sensitive values (API keys, tokens)."""

    def __init__(self, store=None):
        from ...foundation.json_store import db as _default_db

        self.db = store or _default_db
        self.col = self.db.collection("secret_vault")
        self._fernet_key = None

    def _fernet(self):
        if self._fernet_key is None:
            material = hashlib.sha256((settings.JWT_SECRET or "quantos").encode()).digest()
            self._fernet_key = base64.urlsafe_b64encode(material)
        from cryptography.fernet import Fernet

        return Fernet(self._fernet_key)

    def set(self, name, value, store=None):
        """Encrypt and store a secret. Uses Fernet when available."""
        if _HAVE_FERNET:
            encrypted = self._fernet().encrypt(str(value).encode())
            stored = {"alg": "fernet", "data": encrypted.decode()}
        else:
            stored = {"alg": "aes", "data": security.encrypt(str(value))}
        row = self.col.upsert({"id": f"vault:{name}", "name": name, **stored, "updatedAt": int(time.time() * 1000)})
        event_bus.emit("security:vault:set", {"name": name})
        return {"name": name, "updatedAt": row["updatedAt"]}

    def get(self, name, default=None):
        row = self.col.find_one({"name": name})
        if not row:
            return default
        if row.get("alg") == "fernet" and _HAVE_FERNET:
            try:
                return self._fernet().decrypt(row["data"].encode()).decode()
            except Exception:  # noqa: BLE001
                return default
        return security.decrypt(row.get("data", "")) or default

    def delete(self, name):
        row = self.col.find_one({"name": name})
        if row:
            self.col.remove(row["id"])
        event_bus.emit("security:vault:delete", {"name": name})
        return {"name": name, "deleted": bool(row)}

    def list_names(self):
        return [r["name"] for r in self.col.find({})]


class CSRFGuard:
    """Stateless CSRF token issuance/validation bound to a user session."""

    def __init__(self, secret=None):
        self.secret = (secret or settings.JWT_SECRET).encode()

    def issue(self, user_id, nonce=None):
        nonce = nonce or security.random_bytes(16).hex()
        payload = f"{user_id}:{nonce}"
        sig = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()

    def verify(self, token, user_id=None):
        if not token:
            return False
        try:
            raw = base64.urlsafe_b64decode(token.encode()).decode()
            payload, sig = raw.rsplit(":", 1)
        except (ValueError, TypeError):
            return False
        uid, nonce = payload.split(":", 1)
        if user_id and uid != user_id:
            return False
        expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)


class SSRFGuard:
    """Blocks outbound requests to private/internal networks by default."""

    PRIVATE_PATTERNS = [
        re.compile(r"^127\.", re.I),
        re.compile(r"^10\."),
        re.compile(r"^192\.168\."),
        re.compile(r"^172\.(1[6-9]|2[0-9]|3[01])\."),
        re.compile(r"^169\.254\."),
        re.compile(r"^0\."),
        re.compile(r"^localhost$", re.I),
        re.compile(r"^\[::1\]$"),
    ]

    def __init__(self, allow_private=False):
        self.allow_private = bool(allow_private or os.environ.get("SSRF_ALLOW_PRIVATE", "0").lower() in ("1", "true"))

    def host_of(self, url):
        try:
            return urllib.parse.urlparse(url).hostname
        except (ValueError, AttributeError):
            return None

    def validate(self, url):
        host = self.host_of(url)
        if not host:
            return {"allowed": False, "reason": "invalid-url"}
        if self.allow_private:
            return {"allowed": True, "host": host}
        for pattern in self.PRIVATE_PATTERNS:
            if pattern.search(host):
                return {"allowed": False, "reason": "private-network-blocked", "host": host}
        return {"allowed": True, "host": host}


class WebhookSigner:
    """HMAC-SHA256 webhook signature verification."""

    def __init__(self, secret=None):
        self.secret = (secret or os.environ.get("WEBHOOK_SIGNING_SECRET") or settings.JWT_SECRET).encode()

    def sign(self, payload_bytes, timestamp=None):
        timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
        message = f"{timestamp}.{payload_bytes.decode() if isinstance(payload_bytes, bytes) else payload_bytes}"
        sig = hmac.new(self.secret, message.encode(), hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={sig}"

    def verify(self, payload_bytes, signature_header, max_skew_seconds=300):
        if not signature_header:
            return False
        parts = dict((kv.split("=", 1) for kv in signature_header.split(",") if "=" in kv))
        ts = int(parts.get("t", 0) or 0)
        if abs(int(time.time()) - ts) > max_skew_seconds:
            return False
        expected = self.sign(payload_bytes, ts).split("v1=", 1)[1]
        return hmac.compare_digest(expected, parts.get("v1", ""))


totp_provider = TOTP()
secret_vault = SecretVault()
csrf_guard = CSRFGuard()
ssrf_guard = SSRFGuard()
webhook_signer = WebhookSigner()


def init_security_hardening():
    event_bus.emit("security:hardening-ready", {"fernet": _HAVE_FERNET, "totp": True})
    logger.info(f"Security hardening initialized (fernet={'available' if _HAVE_FERNET else 'unavailable'})")
    return {
        "totp": totp_provider,
        "vault": secret_vault,
        "csrf": csrf_guard,
        "ssrf": ssrf_guard,
        "webhookSigner": webhook_signer,
    }
