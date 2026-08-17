"""User management mirroring the Node users/service.js."""
import hashlib
import secrets
import string
import time

from ...foundation.json_store import db
from ...foundation.security import security
from ...foundation.logger import logger
from ...foundation.event_bus import event_bus

ROLES = ["admin", "analyst", "trader", "viewer"]


def _hash_password(password):
    """Return a salted sha256 password hash in ``s1$<salt>$<digest>`` form."""
    salt = security.random_bytes(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"s1${salt}${digest}"


def _parse_salted(stored):
    parts = stored.split("$")
    if len(parts) == 3 and parts[0] == "s1" and parts[1] and parts[2]:
        return parts[1], parts[2]
    return None, None


def _verify_password(password, stored):
    if not stored:
        return False
    if stored.startswith("$2"):
        return security.verify_password(password, stored)
    salt, digest = _parse_salted(stored)
    if salt and digest:
        computed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return computed == digest
    return password == stored


def _upgrade_legacy_password(user, password):
    stored = user.get("passwordHash")
    if not stored:
        return
    if stored.startswith("$2") or not _parse_salted(stored)[0]:
        db.collection("users").update(user["id"], {"passwordHash": _hash_password(password)})


def _generate_temp_password(length=16):
    special = "!@#$%^&*()-_=+"
    chars = string.ascii_letters + string.digits + special
    pwd = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(special),
    ]
    pwd += [secrets.choice(chars) for _ in range(max(0, length - 4))]
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


def init_users():
    col = db.collection("users")
    if col.count() == 0:
        col.insert_many([
            {"username": "admin", "email": "admin@quantos.ai", "role": "admin", "passwordHash": _hash_password("admin123"), "preferences": {"theme": "dark", "currency": "USD"}, "active": True, "createdAt": int(time.time() * 1000)},
            {"username": "trader", "email": "trader@quantos.ai", "role": "trader", "passwordHash": _hash_password("trader123"), "preferences": {"theme": "dark", "currency": "USD"}, "active": True, "createdAt": int(time.time() * 1000)},
            {"username": "analyst", "email": "analyst@quantos.ai", "role": "analyst", "passwordHash": _hash_password("analyst123"), "preferences": {"theme": "system", "currency": "USD"}, "active": True, "createdAt": int(time.time() * 1000)},
        ])
    logger.info("User management initialized")
    return {
        "listUsers": list_users,
        "createUser": create_user,
        "authenticate": authenticate,
        "updatePreferences": update_preferences,
        "listOrganizations": list_organizations,
        "changePassword": change_password,
        "resetPassword": reset_password,
    }


def list_users():
    return [
        {"id": u["id"], "username": u["username"], "email": u["email"], "role": u["role"], "active": u["active"], "preferences": u["preferences"], "createdAt": u["createdAt"]}
        for u in db.collection("users").find({})
    ]


def create_user(user):
    col = db.collection("users")
    if col.find_one({"username": user["username"]}):
        raise ValueError("Username already exists")
    password = user.get("password")
    if not password:
        raise ValueError("Password is required")
    payload = {k: v for k, v in user.items() if k != "password"}
    return col.insert({
        **payload,
        "role": payload.get("role") or "viewer",
        "passwordHash": _hash_password(password),
        "active": True,
        "preferences": user.get("preferences") or {"theme": "dark"},
        "createdAt": int(time.time() * 1000),
    })


def authenticate(username, password):
    from ...modules.security.module import is_locked_out, record_failed_login, reset_login_attempts

    if is_locked_out(username):
        return {"error": "account_locked"}

    user = db.collection("users").find_one({"username": username})
    if not user or not _verify_password(password, user.get("passwordHash")):
        if user:
            record_failed_login(username)
        return None

    reset_login_attempts(username)
    _upgrade_legacy_password(user, password)
    token = security.sign_token({"sub": user["id"], "username": user["username"], "role": user["role"]})
    db.collection("activity_logs").insert({"userId": user["id"], "action": "login", "timestamp": int(time.time() * 1000)})
    event_bus.emit("auth:login", {"userId": user["id"]})
    return {"token": token, "user": {"id": user["id"], "username": user["username"], "email": user.get("email"), "role": user.get("role"), "preferences": user.get("preferences")}}


def change_password(user_id, old_password, new_password):
    from ...modules.security.module import validate_password_policy

    user = db.collection("users").find_one({"id": user_id})
    if not user:
        return {"success": False, "error": "user_not_found"}
    if not _verify_password(old_password, user.get("passwordHash")):
        return {"success": False, "error": "invalid_old_password"}
    policy = validate_password_policy(new_password)
    if not policy["valid"]:
        return {"success": False, "error": "weak_password", "errors": policy["errors"]}
    db.collection("users").update(user_id, {
        "passwordHash": _hash_password(new_password),
        "mustChangePassword": False,
        "updatedAt": int(time.time() * 1000),
    })
    event_bus.emit("auth:passwordChanged", {"userId": user_id})
    return {"success": True}


def reset_password(user_id):
    user = db.collection("users").find_one({"id": user_id})
    if not user:
        raise ValueError("User not found")
    temp_password = _generate_temp_password()
    db.collection("users").update(user_id, {
        "passwordHash": _hash_password(temp_password),
        "mustChangePassword": True,
        "updatedAt": int(time.time() * 1000),
    })
    event_bus.emit("auth:passwordReset", {"userId": user_id})
    return {"userId": user_id, "tempPassword": temp_password, "mustChangePassword": True}


def update_preferences(user_id, preferences):
    return db.collection("users").update(user_id, {"preferences": preferences, "updatedAt": int(time.time() * 1000)})


def list_organizations():
    col = db.collection("organizations")
    if col.count() == 0:
        col.insert_many([
            {"id": "org-1", "name": "QuantOS Holdings", "teams": ["Algo Desk", "Risk", "Research"], "plan": "enterprise", "members": 12, "createdAt": int(time.time() * 1000)},
            {"id": "org-2", "name": "Trading Lab", "teams": ["Traders"], "plan": "pro", "members": 5, "createdAt": int(time.time() * 1000)},
        ])
    return col.find({})
