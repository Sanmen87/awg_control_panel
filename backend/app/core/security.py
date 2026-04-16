from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet
from jose import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def _build_fernet() -> Fernet:
    key_material = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + digest).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = base64.b64decode(password_hash.encode("utf-8"))
    salt = raw[:16]
    stored_digest = raw[16:]
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return hmac.compare_digest(candidate, stored_digest)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expires_at = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload: dict[str, Any] = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def encrypt_value(value: str) -> str:
    return _build_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str) -> str:
    return _build_fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def generate_api_token() -> tuple[str, str]:
    prefix = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
    secret = secrets.token_urlsafe(32)
    return prefix, f"awgcp_{prefix}_{secret}"


def hash_api_token(token: str) -> str:
    digest = hmac.new(settings.secret_key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def api_token_prefix(token: str) -> str | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "awgcp":
        return None
    return parts[1] or None
