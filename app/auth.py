"""Authentication: a signed session cookie for people (same shape as
movingfirm-admin's `admin_session`: user_id.role.exp.sig) and bearer API keys
for other systems. Passwords are scrypt-hashed; API keys stored as sha256."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from app.config import settings
from app.db import db_conn

COOKIE_NAME = "luuri_session"


@dataclass
class Principal:
    id: UUID | None          # user id, None for api keys
    name: str
    role: str                # admin | sales | api
    scopes: tuple[str, ...]  # api keys only

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------- sessions
def _sign(message: str) -> str:
    return hmac.new(settings.SESSION_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


def make_session_token(user_id: UUID, role: str) -> str:
    exp = int(time.time()) + settings.SESSION_TTL_HOURS * 3600
    body = f"{user_id}.{role}.{exp}"
    return f"{body}.{_sign(body)}"


def parse_session_token(token: str) -> tuple[UUID, str] | None:
    parts = token.split(".")
    if len(parts) != 4:
        return None
    body = ".".join(parts[:3])
    if not hmac.compare_digest(_sign(body), parts[3]):
        return None
    try:
        if int(parts[2]) < time.time():
            return None
        return UUID(parts[0]), parts[1]
    except ValueError:
        return None


# ---------------------------------------------------------------- api keys
def generate_api_key() -> tuple[str, str]:
    """Returns (plaintext, hash). Plaintext is shown once."""
    plain = "luuri_" + secrets.token_urlsafe(32)
    return plain, hash_api_key(plain)


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


# ---------------------------------------------------------------- dependencies
def _principal_from_api_key(plain: str) -> Principal | None:
    key_hash = hash_api_key(plain)
    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id, name, scopes FROM api_keys WHERE key_hash = :h AND active"),
            {"h": key_hash},
        ).mappings().first()
        if row is None:
            return None
        conn.execute(text("UPDATE api_keys SET last_used_at = now() WHERE id = :id"), {"id": row["id"]})
    return Principal(id=None, name=row["name"], role="api", scopes=tuple(row["scopes"]))


def _principal_from_cookie(token: str) -> Principal | None:
    parsed = parse_session_token(token)
    if parsed is None:
        return None
    user_id, role = parsed
    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id, name, role FROM users WHERE id = :id AND active"), {"id": user_id}
        ).mappings().first()
    if row is None:
        return None
    return Principal(id=row["id"], name=row["name"], role=row["role"], scopes=())


def current_principal(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        principal = _principal_from_api_key(auth[7:].strip())
        if principal:
            return principal
        raise HTTPException(status_code=401, detail="invalid api key")
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        principal = _principal_from_cookie(cookie)
        if principal:
            return principal
    raise HTTPException(status_code=401, detail="not authenticated")


def require_user(p: Principal = Depends(current_principal)) -> Principal:
    """A person (cookie session) or an api key with the 'write' scope."""
    if p.role == "api" and "write" not in p.scopes:
        raise HTTPException(status_code=403, detail="write scope required")
    return p


def require_admin(p: Principal = Depends(current_principal)) -> Principal:
    if p.role == "admin" or (p.role == "api" and "admin" in p.scopes):
        return p
    raise HTTPException(status_code=403, detail="admin required")


def require_read(p: Principal = Depends(current_principal)) -> Principal:
    return p
