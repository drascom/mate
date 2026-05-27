"""Mate Core — Pi Agent subprocess çağrı katmanı.

Tek arayüz: `call_pi(...)`. Voice MVP (no-tools text-only) ve otonom runner
(allowlist tools + JSON output) ikisi de buradan çağrılır.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from core import config


class PiTimeout(Exception):
    pass


class PiError(Exception):
    def __init__(self, returncode: int, stderr: str):
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"pi exit={returncode}: {stderr[:200]}")


async def call_pi(
    text: str,
    *,
    agent_name: str | None = None,
    session_id: str | None = None,
    tools: list[str] | None = None,
    timeout_sec: int = config.TIMEOUT_SEC,
    cwd: Path | None = None,
) -> tuple[str, float]:
    """Pi binary'yi --print modunda çağır ve yanıtı döndür.

    Args:
        text: Kullanıcı/sistem mesajı.
        agent_name: voice_bridge/agents/<name>.md olarak yüklenir
                    (`--append-system-prompt`). None ise persona eklenmez.
        session_id: Pi --session arg'ı. None ise Pi yeni session yaratır.
        tools: None → --no-tools (text-only, voice MVP davranışı).
               [] → yine --no-tools.
               ['bash', 'write'] → `--tools bash,write` allowlist.
        timeout_sec: Pi cevap vermezse PiTimeout.
        cwd: subprocess cwd. None ise CORE_DIR.

    Returns:
        (stdout_text, elapsed_seconds)

    Raises:
        PiTimeout: Pi belirtilen sürede dönmedi (process kill edildi).
        PiError: Pi non-zero exit. .stderr ilk 500 char.
    """
    args = [
        str(config.PI_BIN),
        "--print",
        "--provider", config.PI_PROVIDER,
        "--model", config.PI_MODEL,
        "--thinking", config.PI_THINKING,
        "--session-dir", str(config.SESSION_DIR),
        "--no-extensions",
    ]
    if not tools:
        args.append("--no-tools")
    else:
        args += ["--tools", ",".join(tools)]
    if agent_name:
        agent_path = resolve_agent_path(agent_name)
        if agent_path:
            args += ["--append-system-prompt", str(agent_path)]
    if session_id:
        args += ["--session", _session_arg(session_id)]
    args.append(text)

    # Pi'nin extensions/skills/memory-vault için Mate'e özel HOME — global
    # ~/.pi/ ile karışmaz, Ubuntu prod'da da repo içinde kalır.
    env = os.environ.copy()
    env["HOME"] = str(config.PI_HOME)

    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd or config.CORE_DIR),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        proc.kill()
        raise PiTimeout(f"pi timeout after {timeout_sec}s")

    elapsed = time.monotonic() - started
    if proc.returncode != 0:
        raise PiError(proc.returncode, err.decode()[:500])

    return out.decode().strip(), elapsed


def _session_arg(session_id: str) -> str:
    """Pi --session UUID veya filename kabul ediyor; UUID ile temiz resume +
    append yapıyor, full-filename ile sessizce append etmiyor. Filename formatı
    `<timestamp>_<UUID>.jsonl` — son underscore'dan sonrası UUID."""
    if not session_id:
        return session_id
    name = session_id
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
    if "_" in name:
        return name.rsplit("_", 1)[-1]
    return name


def resolve_agent_path(agent_name: str):
    """Persona dosyasını autonomous/personas önce, sonra voice_bridge/agents'da ara."""
    candidates = [
        config.CORE_DIR / "autonomous" / "personas" / f"{agent_name}.md",
        config.AGENTS_DIR / f"{agent_name}.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def latest_session_file() -> str | None:
    """Pi'nin yeni yarattığı session'u bul — yeni chat'in ilk çağrısında
    `--session` yoktu, dosya yaratıldı; en yenisini yakala."""
    if not config.SESSION_DIR.exists():
        return None
    files = sorted(
        config.SESSION_DIR.iterdir(),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in files:
        if f.is_file() and f.suffix == ".jsonl":
            return f.name
    return None


def _extract_message_text(content) -> str:
    """Pi content alanı genelde [{"type":"text","text":"..."}] formatında.
    Bazen düz string. İlk text parçasını döndür."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t = part.get("text")
                if isinstance(t, str) and t:
                    return t
        # fallback: ilk dict'in text/content alanı
        first = content[0] if content else None
        if isinstance(first, dict):
            return first.get("text") or first.get("content") or ""
    return ""


# Bridge bazı turn'lerde prompt'un başına `[SİSTEM: ...]` notu ekliyor (pending
# bağlamı / admin context). Pi session jsonl'a bu eklenmiş haliyle düşüyor;
# UI'da gösterirken kullanıcı mesajını saf haliyle yansıtmak için sıyır.
_SYSTEM_NOTE_RE = re.compile(r"\A\[SİSTEM:.*?\]\s*\n+", re.DOTALL)
# Voice-intake persona yanıtı tek JSON kod bloğu — UI'da ham JSON yerine
# tts_reply gösteriliyor (raw kayıt session'da korunur).
_INTAKE_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def _strip_system_notes(text: str) -> str:
    while True:
        m = _SYSTEM_NOTE_RE.match(text)
        if not m:
            break
        text = text[m.end():]
    return text.lstrip()


def _maybe_intake_tts_reply(text: str) -> str | None:
    m = _INTAKE_JSON_RE.search(text)
    candidate = (m.group(1) if m else text).strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        obj = json.loads(candidate)
    except Exception:
        return None
    if isinstance(obj, dict):
        tts = obj.get("tts_reply")
        if isinstance(tts, str) and tts.strip():
            return tts.strip()
    return None


def clean_display_text(text: str, role: str) -> str:
    """UI'a sunulurken role'e göre prompt-internals'ı temizle."""
    if role == "user":
        return _strip_system_notes(text)
    if role == "assistant":
        tts = _maybe_intake_tts_reply(text)
        if tts is not None:
            return tts
    return text


def summarize_session(path: Path) -> dict:
    """Pi session jsonl dosyasını özetle — panel sessions/chat dropdown için.

    Pi formatı: `{"type": "message", "message": {"role": "user|assistant",
    "content": [{"type": "text", "text": "..."}]}}`
    """
    info: dict = {
        "name": path.name,
        "size_kb": round(path.stat().st_size / 1024, 1),
        "mtime": path.stat().st_mtime,
        "messages": 0,
        "first_user": None,
        "last_role": None,
    }
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "message":
                    continue
                msg = obj.get("message") or {}
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                info["messages"] += 1
                info["last_role"] = role
                if role == "user" and info["first_user"] is None:
                    raw_first = _extract_message_text(msg.get("content"))
                    info["first_user"] = clean_display_text(raw_first, role)
    except Exception:
        pass
    return info


def list_sessions(limit: int = 50) -> list[dict]:
    """En son N session özeti (mtime desc)."""
    if not config.SESSION_DIR.exists():
        return []
    files = sorted(
        config.SESSION_DIR.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    return [summarize_session(p) for p in files]


def read_session_messages(session_filename: str) -> list[dict]:
    """Session jsonl'dan kullanıcı/asistan mesajlarını sırayla çıkar."""
    if not session_filename:
        return []
    path = config.SESSION_DIR / session_filename
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict) or obj.get("type") != "message":
                    continue
                msg = obj.get("message") or {}
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                text = clean_display_text(
                    _extract_message_text(msg.get("content")), role
                )
                if text:
                    out.append({"role": role, "text": text})
    except Exception:
        pass
    return out
