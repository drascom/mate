"""Mate Core — /auth/* HTTP endpoint'leri.

GET    /auth/me                   → mevcut kullanıcı + setup_required
GET    /auth/users                → tüm kullanıcılar
POST   /auth/users                → yeni kullanıcı (ilk = otomatik admin)
PATCH  /auth/users/{username}     → admin flag toggle
DELETE /auth/users/{username}     → sil
POST   /auth/login                → current_user'ı değiştir
POST   /auth/logout               → current_user = None
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import auth

router = APIRouter(prefix="/auth", tags=["auth"])


class UserCreateIn(BaseModel):
    username: str
    admin: bool | None = None


class UserPatchIn(BaseModel):
    admin: bool


class LoginIn(BaseModel):
    username: str


@router.get("/me")
async def me() -> dict:
    return {
        "user": auth.current_user(),
        "is_admin": auth.is_admin(),
        "setup_required": auth.setup_required(),
        "user_count": len(auth.list_users()),
    }


@router.get("/users")
async def users() -> dict:
    return {
        "users": auth.list_users(),
        "current_user": (auth.current_user() or {}).get("username"),
    }


@router.post("/users")
async def create(body: UserCreateIn) -> dict:
    try:
        u = auth.create_user(body.username, admin=body.admin)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"user": u, "setup_required": auth.setup_required()}


@router.patch("/users/{username}")
async def patch(username: str, body: UserPatchIn) -> dict:
    if not auth.is_admin():
        raise HTTPException(403, "yalnız admin admin flag'ini değiştirebilir")
    try:
        u = auth.update_user(username, admin=body.admin)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"user": u}


@router.delete("/users/{username}")
async def delete(username: str) -> dict:
    if not auth.is_admin():
        raise HTTPException(403, "yalnız admin kullanıcı silebilir")
    try:
        auth.delete_user(username)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.post("/login")
async def login(body: LoginIn) -> dict:
    try:
        u = auth.login(body.username)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"user": u}


@router.post("/logout")
async def logout() -> dict:
    auth.logout()
    return {"ok": True}
