"""Security foundation mirroring the Node foundation security.js.

Includes password hashing (bcrypt), JWT sign/verify (HS256), AES-CBC encrypt/
decrypt compatible with the Node `iv:data` hex format, and API key auth helpers.
"""
import hashlib
import os
import secrets

import bcrypt
import jwt as pyjwt

from ..config import settings
from .json_store import db
from .logger import logger

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CRYPTO_AVAILABLE = False


class Security:
    def hash_password(self, password):
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(10)).decode("utf-8")

    def verify_password(self, password, hashed):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    def sign_token(self, payload):
        return pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

    def verify_token(self, token):
        return pyjwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])

    def random_bytes(self, n=32):
        return secrets.token_hex(n)

    def _aes_key(self):
        return hashlib.sha256(settings.JWT_SECRET.encode("utf-8")).digest()

    def encrypt(self, plain):
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package required for encryption")
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self._aes_key()), modes.CBC(iv))
        encryptor = cipher.encryptor()
        data = str(plain).encode("utf-8")
        pad_len = 16 - (len(data) % 16)
        data += bytes([pad_len]) * pad_len
        enc = encryptor.update(data) + encryptor.finalize()
        return f"{iv.hex()}:{enc.hex()}"

    def decrypt(self, payload):
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package required for decryption")
        iv_hex, data_hex = str(payload).split(":")
        iv = bytes.fromhex(iv_hex)
        cipher = Cipher(algorithms.AES(self._aes_key()), modes.CBC(iv))
        decryptor = cipher.decryptor()
        data = decryptor.update(bytes.fromhex(data_hex)) + decryptor.finalize()
        pad_len = data[-1]
        return data[:-pad_len].decode("utf-8")

    def validate_api_key(self, key):
        import re
        if not key or len(key) < 16:
            return False
        return bool(re.match(r"^[A-Za-z0-9_\-]+$", key))


security = Security()


def extract_credentials(request):
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key")
    if auth.startswith("Bearer "):
        return {"type": "jwt", "token": auth[7:]}
    if api_key:
        return {"type": "apikey", "token": api_key}
    return None


def authenticate_request(request):
    creds = extract_credentials(request)
    if not creds:
        return None
    if creds["type"] == "jwt":
        try:
            payload = security.verify_token(creds["token"])
            return {"id": payload.get("sub"), "username": payload.get("username"), "role": payload.get("role"), "type": "jwt"}
        except Exception:
            return None
    if creds["type"] == "apikey":
        digest = hashlib.sha256(creds["token"].encode("utf-8")).hexdigest()
        row = db.collection("api_keys").find_one({"keyHash": digest})
        if not row or row.get("revoked"):
            return None
        return {"id": row.get("id"), "username": row.get("name"), "role": row.get("role"), "type": "apikey"}
    return None


def init_security():
    logger.info("Security foundation initialized")
    return security
