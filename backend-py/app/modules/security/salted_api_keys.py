"""Salted API key hashing (additive Module 3.3).

Stores API keys as ``sha256(salt + key)`` digests with a per-key random salt,
following the exact ``s1$<salt>$<digest>`` format already used for passwords in
``users/service.py``. Raw keys are never persisted — they are returned to the
caller exactly once at creation time and then only the salted digest remains.

Provides a compatibility ``verify`` that accepts both salted (s1) and legacy
bare-sha256 (unsalted) rows so existing stored keys keep working until rotated.
"""
import hashlib
import secrets
import time

from ...foundation.json_store import db
from ...foundation.logger import logger
from ...foundation.security import security

ALG = "s1"


def _random_salt(length=32):
    return security.random_bytes(length)


def hash_api_key(raw_key, salt=None):
    """Return ``s1$<salt>$<sha256(salt+key)>`` — no plaintext survives."""
    salt = salt or _random_salt()
    digest = hashlib.sha256(f"{salt}{raw_key}".encode("utf-8")).hexdigest()
    return f"{ALG}${salt}${digest}"


def verify_api_key_hash(raw_key, stored):
    """Verify a raw key against a stored hash (salted or legacy unsalted)."""
    if not raw_key or not stored:
        return False
    if not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) == 3 and parts[0] == ALG and parts[1] and parts[2]:
        salt, digest = parts[1], parts[2]
        computed = hashlib.sha256(f"{salt}{raw_key}".encode("utf-8")).hexdigest()
        return secrets.compare_digest(computed, digest)
    if len(parts) == 1 and len(stored) == 64:
        # Legacy unsalted sha256 (pre-module). Verify and note for rotation.
        try:
            legacy = int(stored, 16)
            computed = int(hashlib.sha256(str(raw_key).encode("utf-8")).hexdigest(), 16)
            return secrets.compare_digest(computed, legacy)
        except (ValueError, TypeError):
            return False
    return False


def create_salted_api_key(name, role="viewer"):
    """Create an API key row storing only the salted digest."""
    raw_key = security.random_bytes(32)
    salt = _random_salt()
    col = db.collection("api_keys")
    row = col.insert({
        "name": name,
        "role": role,
        "keyHash": hash_api_key(raw_key, salt),
        "keySalt": salt,
        "whitelist": [],
        "createdAt": int(time.time() * 1000),
    })
    return {**_sanitize(row), "key": raw_key}


def _sanitize(row):
    out = {k: v for k, v in row.items() if k not in ("key", "keyHash", "keySalt")}
    out["revoked"] = bool(row.get("revoked", False))
    return out


def verify_api_key(raw_key):
    """Locate and verify a raw API key against stored digests."""
    if not raw_key:
        return False
    for row in db.collection("api_keys").find({}):
        if row.get("revoked"):
            continue
        stored = row.get("keyHash") or row.get("keyHashLegacy")
        if stored and verify_api_key_hash(raw_key, stored):
            return True
    return False


def rotate_api_key(key_id):
    """Revoke the old row and return a fresh raw key (salted hash stored)."""
    col = db.collection("api_keys")
    row = col.find_one({"id": key_id})
    if not row:
        return None
    col.update(key_id, {"revoked": True, "rotatedAt": int(time.time() * 1000)})
    return create_salted_api_key(row.get("name") or "Rotated Key", row.get("role") or "viewer")


def migrate_legacy_keys():
    """Upgrade legacy bare-sha256 rows to salted digests.

    Because the raw key is not recoverable from a digest, legacy keys are
    rotated: the old row is revoked and a brand new salted key is created. The
    new raw value is only returned in the returned list (never persisted).
    """
    col = db.collection("api_keys")
    migrated = []
    for row in col.find({}):
        stored = row.get("keyHash") or ""
        is_salted = isinstance(stored, str) and stored.startswith(f"{ALG}$")
        if row.get("revoked") or is_salted:
            continue
        revoked = col.update(row["id"], {"revoked": True, "legacyReplaced": True})
        created = create_salted_api_key(row.get("name") or row.get("id") or "Legacy Key", row.get("role") or "viewer")
        migrated.append({**created, "replaced": revoked["id"]})
    if migrated:
        logger.warn(f"Migrated {len(migrated)} legacy API keys to salted digests (raw values rotated)")
    return migrated


def api_key_count():
    return db.collection("api_keys").count()


def init_salted_api_keys():
    migrated = migrate_legacy_keys()
    logger.info(f"Salted API key module initialized ({len(migrated)} legacy keys migrated)")
    return {
        "create": create_salted_api_key,
        "verify": verify_api_key,
        "rotate": rotate_api_key,
        "migrate": migrate_legacy_keys,
        "count": api_key_count,
    }
