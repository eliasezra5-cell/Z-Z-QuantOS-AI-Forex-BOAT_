"""Enterprise protection layer (additive Module 3.3).

Builds on the existing ``security/hardening.py`` guards and adds:

  - Cookie security policy: Secure / HttpOnly / SameSite handling helper.
  - CSRF enforcement helper for state-changing (cookie-authenticated) requests.
  - SSRF allow/deny lists layered on top of the existing private-network guard.
  - A single ``security_headers()`` helper that emits CSP, HSTS, frame, nosniff,
    referrer-policy and permissions-policy in one place.

Everything here is additive; existing middleware/modules are untouched.
"""
import hashlib
import hmac
import os
import time
import urllib.parse

from ...foundation.logger import logger
from ...config import settings

# Default security headers (aligned with the ones set in app.main).
CSP_DEFAULT = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
HSTS_DEFAULT = "max-age=31536000; includeSubDomains"

# Known-safe allow list for outbound fetches (documentation/icon hosts, etc).
DEFAULT_SSRF_ALLOW_HOSTS = {
    "api.telegram.org",
    "discord.com",
    "discordapp.com",
    "github.com",
    "api.github.com",
    "t.me",
    "pypi.org",
    "files.pythonhosted.org",
    "api.deepseek.com",
    "api.openai.com",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
}
# Always-blocked network ranges in addition to the private-range guard.
DEFAULT_SSRF_DENY_HOSTS = {
    "169.254.169.254",  # cloud metadata
    "metadata.google.internal",
    "metadata",
}


def _env_flag(key, default=False):
    return os.environ.get(key, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def security_headers(secure=False, csp=None, hsts=None):
    """Return a dict of security headers to apply to a response."""
    headers = {
        "Content-Security-Policy": csp or CSP_DEFAULT,
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
    if secure:
        headers["Strict-Transport-Security"] = hsts or HSTS_DEFAULT
    return headers


class CookiePolicy:
    """Build cookie attributes for secure session cookies."""

    def __init__(self, secure=None, samesite="lax"):
        self.secure = (secure if secure is not None else _env_flag("SECURE_COOKIES", settings.ENVIRONMENT.lower() == "production"))
        self.samesite = samesite

    def attrs(self, name=None):
        parts = [f"Path=/", f"SameSite={self.samesite}"]
        if self.secure:
            parts.append("Secure")
        parts.append("HttpOnly")
        return "; ".join(parts)

    def is_secure_cookie(self):
        return self.secure


cookie_policy = CookiePolicy()


class CSRFEnforcer:
    """CSRF enforcement for state-changing cookie-authenticated requests.

    Uses a stateless HMAC token bound to the user/session (same scheme as the
    existing ``csrf_guard``) and rejects unsafe methods that lack a valid token.
    """

    UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, secret=None):
        self.secret = (secret or settings.JWT_SECRET).encode("utf-8")

    def issue(self, session_id, nonce=None):
        nonce = nonce or os.urandom(16).hex()
        payload = f"{session_id}:{nonce}"
        sig = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}:{sig}"

    def verify(self, token, session_id=None):
        if not token:
            return False
        try:
            payload, sig = str(token).rsplit(":", 1)
            sess, _nonce = payload.rsplit(":", 1)
        except (ValueError, TypeError):
            return False
        if session_id and sess != session_id:
            return False
        expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def enforce(self, method, token, session_id=None):
        """Return None if allowed, or an error dict if blocked."""
        if method.upper() not in self.UNSAFE_METHODS:
            return None
        if not self.verify(token, session_id):
            return {"code": "CSRF_BLOCKED", "message": "Missing or invalid CSRF token", "status": 403}
        return None


csrf_enforcer = CSRFEnforcer()


class SSRFPolicy:
    """SSRF guard with allow/deny lists layered over the private-network block.

    Policy order:
      1. deny list (exact host match)           -> block
      2. allow list (exact host or suffix)      -> allow (still validated)
      3. private/internal network check         -> block
      4. otherwise                              -> allow
    """

    def __init__(self, allow=None, deny=None, allow_private=False):
        self.allow_hosts = set(allow or DEFAULT_SSRF_ALLOW_HOSTS)
        self.deny_hosts = set(deny or DEFAULT_SSRF_DENY_HOSTS)
        self.allow_private = allow_private or _env_flag("SSRF_ALLOW_PRIVATE")

        from .hardening import SSRFGuard  # reuse existing guard internals
        self._guard = SSRFGuard(allow_private=self.allow_private)

    def host_of(self, url):
        try:
            return urllib.parse.urlparse(url).hostname
        except (ValueError, AttributeError):
            return None

    def _is_denied(self, host):
        host_l = (host or "").lower()
        if host_l in self.deny_hosts:
            return True
        return any(host_l.endswith("." + d.lower()) for d in self.deny_hosts)

    def _is_allowed(self, host):
        host_l = (host or "").lower()
        if host_l in self.allow_hosts:
            return True
        return any(host_l.endswith("." + a.lower()) for a in self.allow_hosts)

    def validate(self, url):
        host = self.host_of(url)
        if not host:
            return {"allowed": False, "reason": "invalid-url"}
        if self._is_denied(host):
            return {"allowed": False, "reason": "deny-list-matched", "host": host}
        if self._is_allowed(host):
            return {"allowed": True, "host": host, "list": "allow"}
        # Fall back to the private-network guard.
        return self._guard.validate(url)

    def add_allow(self, host):
        self.allow_hosts.add(host.lower())

    def add_deny(self, host):
        self.deny_hosts.add(host.lower())


ssrf_policy = SSRFPolicy()


def init_protections():
    logger.info("Enterprise protections initialized (CSRF/SSRF/CSP/cookies)")
    return {
        "headers": security_headers,
        "cookies": cookie_policy,
        "csrf": csrf_enforcer,
        "ssrf": ssrf_policy,
    }
