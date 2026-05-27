"""Mate Core — kullanıcı tabanlı basit auth.

`state/users.json`: tek dosyada kayıtlı kullanıcılar + aktif kullanıcı.
Şifre yok, sadece username. "Production auth" değil — LAN/dev için yeterli güveni
sağlar. Voice "yönetici:" / "admin:" prefix admin context'i o turn için tetikler;
panel'de admin kullanıcı + yönetici toggle ile agentic_pi açılır.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from core import config

_USERS_FILE = config.STATE_DIR / "users.json"
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_ADMIN_PREFIX_RE = re.compile(r"^\s*(?:yönetici|yonetici|admin)\s*[:：]\s*", re.IGNORECASE)
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _empty_doc() -> dict[str, Any]:
    return {"users": [], "current_user": None}


def _load_unlocked() -> dict[str, Any]:
    if not _USERS_FILE.exists():
        return _empty_doc()
    try:
        doc = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        # Bozulmuş dosya → güvenli fallback. (Bilinçli silme yok; manuel müdahale gerek.)
        return _empty_doc()
    if not isinstance(doc, dict):
        return _empty_doc()
    doc.setdefault("users", [])
    doc.setdefault("current_user", None)
    if not isinstance(doc["users"], list):
        doc["users"] = []
    return doc


def _save_unlocked(doc: dict[str, Any]) -> None:
    _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _USERS_FILE)


def load() -> dict[str, Any]:
    with _lock:
        return _load_unlocked()


def setup_required() -> bool:
    doc = load()
    return len(doc["users"]) == 0


def list_users() -> list[dict[str, Any]]:
    return load()["users"]


def get_user(username: str) -> dict[str, Any] | None:
    for u in list_users():
        if u.get("username") == username:
            return u
    return None


def current_user() -> dict[str, Any] | None:
    doc = load()
    name = doc.get("current_user")
    if not name:
        return None
    for u in doc["users"]:
        if u.get("username") == name:
            return u
    return None


def is_admin() -> bool:
    u = current_user()
    return bool(u and u.get("admin"))


def _validate_username(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("username string olmalı")
    cleaned = name.strip().lower()
    if not _USERNAME_RE.match(cleaned):
        raise ValueError("username: a-z, 0-9, _ ve - ile, 1-32 karakter; harf/rakamla başla")
    return cleaned


def create_user(username: str, admin: bool | None = None) -> dict[str, Any]:
    """Yeni kullanıcı. İlk kullanıcı zorla admin (setup mode).

    Args:
        admin: None ise: ilk kullanıcı için True, sonrakiler için False.
               Bool gelirse ilk kullanıcıda yine True'ya zorlanır.
    """
    name = _validate_username(username)
    with _lock:
        doc = _load_unlocked()
        if any(u.get("username") == name for u in doc["users"]):
            raise ValueError(f"kullanıcı zaten var: {name}")
        is_first = len(doc["users"]) == 0
        flag = True if is_first else bool(admin)
        user = {"username": name, "admin": flag, "created": _now_iso()}
        doc["users"].append(user)
        # Setup mode: ilk kullanıcı otomatik giriş yapmış sayılır.
        if is_first:
            doc["current_user"] = name
        _save_unlocked(doc)
        return user


def update_user(username: str, *, admin: bool) -> dict[str, Any]:
    name = _validate_username(username)
    with _lock:
        doc = _load_unlocked()
        target = next((u for u in doc["users"] if u.get("username") == name), None)
        if not target:
            raise ValueError(f"kullanıcı yok: {name}")
        # Son admin'i adminlikten düşürme
        if target.get("admin") and not admin:
            other_admins = [
                u for u in doc["users"]
                if u.get("admin") and u.get("username") != name
            ]
            if not other_admins:
                raise ValueError("son admin'i adminlikten düşüremezsin")
        target["admin"] = bool(admin)
        _save_unlocked(doc)
        return target


def delete_user(username: str) -> None:
    name = _validate_username(username)
    with _lock:
        doc = _load_unlocked()
        target = next((u for u in doc["users"] if u.get("username") == name), None)
        if not target:
            raise ValueError(f"kullanıcı yok: {name}")
        if doc.get("current_user") == name:
            raise ValueError("kendini silemezsin; önce başka kullanıcıya geç")
        if target.get("admin"):
            other_admins = [
                u for u in doc["users"]
                if u.get("admin") and u.get("username") != name
            ]
            if not other_admins:
                raise ValueError("son admin silinemez")
        doc["users"] = [u for u in doc["users"] if u.get("username") != name]
        _save_unlocked(doc)


def login(username: str) -> dict[str, Any]:
    name = _validate_username(username)
    with _lock:
        doc = _load_unlocked()
        target = next((u for u in doc["users"] if u.get("username") == name), None)
        if not target:
            raise ValueError(f"kullanıcı yok: {name}")
        doc["current_user"] = name
        _save_unlocked(doc)
        return target


def logout() -> None:
    with _lock:
        doc = _load_unlocked()
        doc["current_user"] = None
        _save_unlocked(doc)


def strip_admin_prefix(text: str) -> tuple[str, bool]:
    """Mesajın başında 'yönetici:' / 'admin:' varsa kaldır, True dön.

    Prefix yalnız mesajın başında geçerli — içinde geçmesi tetiklemez (yanlış
    pozitif önlemek için)."""
    if not isinstance(text, str):
        return text, False
    m = _ADMIN_PREFIX_RE.match(text)
    if not m:
        return text, False
    return text[m.end():].lstrip(), True


def admin_context_for_request(text: str, *, panel_admin_mode: bool = False) -> tuple[str, bool]:
    """Bridge bir chat mesajı aldığında admin context'in aktif olup olmadığını
    belirler ve mesajın prefix'ini temizler.

    Kurallar:
      - Voice "yönetici:" / "admin:" prefix → admin context (login state'inden
        bağımsız). Sebep: iOS app login geçmiyor ama Doktor'un fiziksel/ses
        erişimi LAN'da güvenli sayılıyor.
      - Panel admin_mode toggle → SADECE current_user.admin == True ise geçerli.

    Returns:
        (cleaned_text, is_admin_context)
    """
    cleaned, had_prefix = strip_admin_prefix(text)
    panel_grants = bool(panel_admin_mode) and is_admin()
    return cleaned, (had_prefix or panel_grants)
