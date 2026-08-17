"""Enterprise security module mirroring the Node security/module.js."""
import hashlib
import time

from ...foundation.logger import logger
from ...foundation.json_store import db
from ...foundation.security import security
from ...config import settings
from ...foundation.event_bus import event_bus  # noqa: F401

MAX_LOGIN_ATTEMPTS = 5
lockout_minutes = 15


def _hash_key(raw_key):
    """Return the sha256 hex digest used as the stored representation of a raw key."""
    return hashlib.sha256(str(raw_key).encode("utf-8")).hexdigest()


def _sanitize_key_doc(k):
    """Project an api_key row to a public shape that never leaks ``key`` or ``keyHash``."""
    return {
        "id": k.get("id"),
        "name": k.get("name"),
        "role": k.get("role"),
        "whitelist": k.get("whitelist") or [],
        "createdAt": k.get("createdAt"),
        "revoked": bool(k.get("revoked", False)),
    }


def _migrate_plaintext_keys():
    """Replace any legacy rows that store a raw ``key`` with a keyHash-only row.

    The old plaintext key is unrecoverable; it is rotated to a fresh random key
    whose raw value is only ever kept in memory and never persisted.
    """
    col = db.collection("api_keys")
    changed = False
    for row in col.rows:
        if "key" in row and "keyHash" not in row:
            raw_key = security.random_bytes(32)
            row.pop("key", None)
            row["keyHash"] = _hash_key(raw_key)
            row["rotated"] = True
            changed = True
    if changed:
        col._persist()
        logger.warn("Migrated legacy plaintext API keys: raw values rotated, only keyHash stored")


def init_security_module():
    col = db.collection("api_keys")
    if col.count() == 0:
        raw_key = security.random_bytes(24)
        col.insert({
            "id": "default-key",
            "name": "Default Read Key",
            "keyHash": _hash_key(raw_key),
            "role": "viewer",
            "whitelist": [],
            "createdAt": int(time.time() * 1000),
        })
    _migrate_plaintext_keys()
    logger.info("Enterprise security module initialized")
    return {
        "listApiKeys": list_api_keys,
        "createApiKey": create_api_key,
        "getAuditLogs": get_audit_logs,
        "getSecurityDashboard": get_security_dashboard,
        "createSession": create_session,
        "validateSession": validate_session,
        "revokeSession": revoke_session,
        "revokeAllSessions": revoke_all_sessions,
        "listSessions": list_sessions,
        "verifyApiKey": verify_api_key,
        "rotateKey": rotate_key,
        "validatePasswordPolicy": validate_password_policy,
        "checkLoginAttempts": check_login_attempts,
        "recordFailedLogin": record_failed_login,
        "resetLoginAttempts": reset_login_attempts,
        "isLockedOut": is_locked_out,
    }


def list_api_keys():
    return [_sanitize_key_doc(k) for k in db.collection("api_keys").find({})]


def create_api_key(name, role="viewer"):
    raw_key = security.random_bytes(32)
    row = db.collection("api_keys").insert({
        "name": name,
        "role": role,
        "keyHash": _hash_key(raw_key),
        "whitelist": [],
        "createdAt": int(time.time() * 1000),
    })
    log_audit(None, "apikey.create", {"keyId": row["id"], "name": name, "role": role})
    return {**_sanitize_key_doc(row), "key": raw_key}


def verify_api_key(raw_key):
    if not raw_key:
        return False
    row = db.collection("api_keys").find_one({"keyHash": _hash_key(raw_key)})
    if not row:
        return False
    return not row.get("revoked", False)


def rotate_key(key_id):
    col = db.collection("api_keys")
    row = col.find_one({"id": key_id})
    if not row:
        raise ValueError("API key not found")
    col.update(key_id, {"revoked": True})
    raw_key = security.random_bytes(32)
    new_row = col.insert({
        "name": row.get("name", "Rotated Key"),
        "role": row.get("role", "viewer"),
        "keyHash": _hash_key(raw_key),
        "whitelist": row.get("whitelist") or [],
        "createdAt": int(time.time() * 1000),
    })
    log_audit(None, "apikey.rotate", {"keyId": key_id, "newKeyId": new_row["id"]})
    return {"id": new_row["id"], "name": new_row["name"], "role": new_row["role"], "key": raw_key}


def create_session(user_id, metadata=None):
    token = security.random_bytes(32)
    now = int(time.time() * 1000)
    return db.collection("sessions").insert({
        "userId": user_id,
        "token": token,
        "metadata": metadata or {},
        "expiresAt": now + settings.JWT_EXPIRES_SECONDS * 1000,
        "active": True,
        "createdAt": now,
    })


def validate_session(token):
    if not token:
        return False
    row = db.collection("sessions").find_one({"token": token})
    if not row:
        return False
    if not row.get("active", False):
        return False
    return row.get("expiresAt", 0) > int(time.time() * 1000)


def revoke_session(token):
    if not token:
        return False
    row = db.collection("sessions").find_one({"token": token})
    if not row:
        return False
    db.collection("sessions").update(row["id"], {"active": False})
    return True


def revoke_all_sessions(user_id):
    col = db.collection("sessions")
    revoked = 0
    for row in col.find({"userId": user_id}):
        if row.get("active", False):
            col.update(row["id"], {"active": False})
            revoked += 1
    return revoked


def list_sessions(user_id):
    return [
        {
            "id": s.get("id"),
            "userId": s.get("userId"),
            "metadata": s.get("metadata") or {},
            "expiresAt": s.get("expiresAt"),
            "active": bool(s.get("active", False)),
            "createdAt": s.get("createdAt"),
        }
        for s in db.collection("sessions").find({"userId": user_id})
    ]


def validate_password_policy(password):
    errors = []
    if not isinstance(password, str) or len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    if isinstance(password, str) and not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    if isinstance(password, str) and not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    if isinstance(password, str) and not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")
    if isinstance(password, str) and not any(not c.isalnum() and not c.isspace() for c in password):
        errors.append("Password must contain at least one special character")
    return {"valid": not errors, "errors": errors}


def _lockout_ms():
    return lockout_minutes * 60 * 1000


def record_failed_login(username):
    col = db.collection("login_attempts")
    now = int(time.time() * 1000)
    row = col.find_one({"username": username})
    if row is None:
        return col.insert({"username": username, "attempts": 1, "firstFailedAt": now, "updatedAt": now})
    if row.get("attempts", 0) >= MAX_LOGIN_ATTEMPTS and now - row.get("firstFailedAt", now) >= _lockout_ms():
        return col.update(row["id"], {"attempts": 1, "firstFailedAt": now, "updatedAt": now})
    return col.update(row["id"], {"attempts": row.get("attempts", 0) + 1, "updatedAt": now})


def reset_login_attempts(username):
    row = db.collection("login_attempts").find_one({"username": username})
    if row is None:
        return None
    return db.collection("login_attempts").remove(row["id"])


def check_login_attempts(username):
    row = db.collection("login_attempts").find_one({"username": username})
    if row is None:
        return {"username": username, "attempts": 0, "locked": False, "lockoutRemainingMs": 0}
    attempts = row.get("attempts", 0)
    lockout_until = row.get("firstFailedAt", 0) + _lockout_ms()
    now = int(time.time() * 1000)
    locked = attempts >= MAX_LOGIN_ATTEMPTS and now < lockout_until
    return {
        "username": username,
        "attempts": attempts,
        "locked": locked,
        "lockoutRemainingMs": max(0, lockout_until - now) if locked else 0,
    }


def is_locked_out(username):
    return bool(check_login_attempts(username)["locked"])


def get_audit_logs(params=None):
    params = params or {}
    logs = db.collection("activity_logs").find({})
    if params.get("action"):
        logs = [l for l in logs if l["action"] == params["action"]]
    return sorted(logs, key=lambda l: l["timestamp"], reverse=True)[: int(params.get("limit") or 100)]


def log_audit(user_id, action, meta=None):
    db.collection("activity_logs").insert({"userId": user_id, "action": action, "meta": meta or {}, "timestamp": int(time.time() * 1000)})


def get_security_dashboard():
    keys = db.collection("api_keys").find({})
    logs = db.collection("activity_logs").find({})
    sessions = db.collection("sessions").find({})
    attempts = db.collection("login_attempts").find({})
    now = int(time.time() * 1000)
    active_sessions = [s for s in sessions if s.get("active", False) and s.get("expiresAt", 0) > now]
    active_by_user = {}
    for s in active_sessions:
        active_by_user[s.get("userId")] = active_by_user.get(s.get("userId"), 0) + 1
    locked_out = [
        a for a in attempts
        if a.get("attempts", 0) >= MAX_LOGIN_ATTEMPTS and a.get("firstFailedAt", 0) + _lockout_ms() > now
    ]
    return {
        "apiKeys": len(keys),
        "activeSessions": len(active_sessions),
        "activeSessionsBreakdown": {"total": len(active_sessions), "byUser": active_by_user},
        "lockedOutAccounts": len(locked_out),
        "auditEvents": len(logs),
        "recentLogin": [{"at": l["timestamp"]} for l in logs if l["action"] == "login"][-5:],
        "mfaEnabled": False,
        "ipWhitelistActive": False,
        "authEnabled": settings.security["authEnabled"],
        "rateLimit": {"windowMs": settings.rate_limit["windowMs"], "max": settings.rate_limit["max"]},
        "encryption": "AES-256-CBC",
        "passwordPolicy": "bcrypt + 10 rounds",
    }
