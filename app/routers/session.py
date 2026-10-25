from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from app.auth import (
    COOKIE_NAME,
    Principal,
    current_principal,
    generate_api_key,
    hash_password,
    make_session_token,
    require_admin,
    verify_password,
)
from app.config import settings
from app.db import db_conn

router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


@router.post("/login")
def login(body: LoginRequest, response: Response):
    with db_conn() as conn:
        row = conn.execute(
            text("SELECT id, name, role, password_hash FROM users WHERE lower(email) = lower(:e) AND active"),
            {"e": body.email},
        ).mappings().first()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Väärä sähköposti tai salasana")
    token = make_session_token(row["id"], row["role"])
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", secure=False,
        max_age=settings.SESSION_TTL_HOURS * 3600, path="/",
    )
    return {"id": str(row["id"]), "name": row["name"], "role": row["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(current_principal)):
    phone = None
    if p.id:
        with db_conn() as conn:
            phone = conn.execute(text("SELECT phone_e164 FROM users WHERE id=:id"), {"id": p.id}).scalar()
    return {"id": str(p.id) if p.id else None, "name": p.name, "role": p.role, "scopes": list(p.scopes), "phone_e164": phone}


class MePatch(BaseModel):
    phone: str | None = Field(default=None, max_length=50, description="own phone; the provider rings this first")


@router.patch("/me")
def patch_me(body: MePatch, p: Principal = Depends(current_principal)):
    if p.id is None:
        raise HTTPException(status_code=403, detail="not a user")
    from app.phone import canonical_phone

    phone = canonical_phone(body.phone) if body.phone else None
    if body.phone and (not phone or not (phone.startswith("+") and len(phone) >= 8)):
        raise HTTPException(status_code=422, detail="Puhelinnumero ei kelpaa")
    with db_conn() as conn:
        conn.execute(text("UPDATE users SET phone_e164=:ph WHERE id=:id"), {"ph": phone, "id": p.id})
    return {"phone_e164": phone}


# ---------------------------------------------------------------- users (admin)
class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="sales", pattern="^(admin|sales)$")
    password: str = Field(min_length=8, max_length=200)


@router.get("/users")
def list_users(_: Principal = Depends(require_admin)):
    with db_conn() as conn:
        rows = conn.execute(
            text("SELECT id, email, name, role, active, created_at FROM users ORDER BY created_at")
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        exists = conn.execute(text("SELECT 1 FROM users WHERE lower(email)=lower(:e)"), {"e": body.email}).first()
        if exists:
            raise HTTPException(status_code=409, detail="Sähköposti on jo käytössä")
        row = conn.execute(
            text(
                "INSERT INTO users (email, name, role, password_hash) VALUES (:e, :n, :r, :h) "
                "RETURNING id, email, name, role, active, created_at"
            ),
            {"e": body.email, "n": body.name, "r": body.role, "h": hash_password(body.password)},
        ).mappings().one()
    return dict(row)


class UserPatch(BaseModel):
    active: bool | None = None
    role: str | None = Field(default=None, pattern="^(admin|sales)$")
    password: str | None = Field(default=None, min_length=8, max_length=200)


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        if body.active is not None:
            conn.execute(text("UPDATE users SET active=:a WHERE id=:id"), {"a": body.active, "id": user_id})
        if body.role is not None:
            conn.execute(text("UPDATE users SET role=:r WHERE id=:id"), {"r": body.role, "id": user_id})
        if body.password is not None:
            conn.execute(
                text("UPDATE users SET password_hash=:h WHERE id=:id"), {"h": hash_password(body.password), "id": user_id}
            )
        row = conn.execute(
            text("SELECT id, email, name, role, active, created_at FROM users WHERE id=:id"), {"id": user_id}
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return dict(row)


# ---------------------------------------------------------------- api keys (admin)
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read"])


@router.get("/api-keys")
def list_api_keys(_: Principal = Depends(require_admin)):
    with db_conn() as conn:
        rows = conn.execute(
            text("SELECT id, name, scopes, active, created_at, last_used_at FROM api_keys ORDER BY created_at")
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyCreate, _: Principal = Depends(require_admin)):
    allowed = {"read", "write", "admin"}
    scopes = sorted(set(body.scopes) & allowed)
    if not scopes:
        raise HTTPException(status_code=422, detail="scopes must include read, write or admin")
    plain, key_hash = generate_api_key()
    with db_conn() as conn:
        row = conn.execute(
            text("INSERT INTO api_keys (name, key_hash, scopes) VALUES (:n, :h, :s) RETURNING id, name, scopes, created_at"),
            {"n": body.name, "h": key_hash, "s": scopes},
        ).mappings().one()
    return {**dict(row), "key": plain}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: str, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        conn.execute(text("UPDATE api_keys SET active=false WHERE id=:id"), {"id": key_id})
    return {"ok": True}
