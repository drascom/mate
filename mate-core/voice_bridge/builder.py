"""Mate Core — agent-builder persona için JSON taslak parse + commit.

agent-builder persona'sı Pi'ye `{filename, content}` JSON taslağı dönmesini
söylüyor; bu modül o taslağı parse edip path/format validasyonu sonrası
diske yazıyor. Hata durumunda voice-uyumlu Türkçe cümle döner.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import config
from voice_bridge.persona import parse_agent_triggers

# Pi tool kullanamadığı için (--no-tools) sadece text üretir; o text içinde
# `{filename, content}` JSON taslak bekliyoruz.
_BUILDER_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)
_RESERVED_AGENT_NAMES = {"voice-default", "agent-builder"}


def try_parse_builder_draft(reply: str) -> dict | None:
    m = _BUILDER_JSON_RE.search(reply)
    candidate = m.group(1) if m else reply.strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        obj = json.loads(candidate)
    except Exception:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("filename"), str) and isinstance(obj.get("content"), str):
        return obj
    return None


def commit_builder_draft(draft: dict) -> tuple[bool, str]:
    """Returns (success, user-facing TTS message). Hatalar 4xx/5xx yerine
    voice-uyumlu cümleler döner."""
    fn: str = draft["filename"].strip()
    content: str = draft["content"]

    if not fn.startswith(("agents/", "skills/")):
        return False, f"Taslakta yasak bir dosya yolu var Doktor: {fn}. Yaratım iptal edildi."
    if ".." in fn or fn.endswith("/") or "\\" in fn:
        return False, "Taslakta güvensiz bir dosya yolu var Doktor. Yaratım iptal edildi."
    if not fn.endswith(".md"):
        return False, "Dosya adı .md ile bitmeli Doktor. Yaratım iptal edildi."

    name = Path(fn).stem
    if name in _RESERVED_AGENT_NAMES:
        return False, f"{name} çekirdek persona, üzerine yazılamaz Doktor."

    first_line = content.split("\n", 1)[0].strip()
    if first_line != "---":
        return False, "Taslakta frontmatter eksik Doktor — ilk satır üç tire olmalıydı. Yeniden denemek ister misin?"
    if "triggers:" not in content[:300]:
        return False, "Taslakta triggers listesi yok Doktor. Yeniden denemek ister misin?"

    # voice_bridge altında: agents/<name>.md → mate-core/voice_bridge/agents/<name>.md
    # skills/ ileride farklı bir hedef olabilir; şimdilik aynı yerel hiyerarşi.
    target = config.CORE_DIR / "voice_bridge" / fn
    if target.exists():
        return False, f"{name} zaten var Doktor — üzerine yazmak için açık onay söylemen gerek."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return False, f"Dosya yazılırken hata: {exc}. Tekrar denemek ister misin?"

    triggers = parse_agent_triggers(target)
    sample = ", ".join(triggers[:3]) if triggers else "(trigger okunamadı)"
    kind = "persona" if fn.startswith("agents/") else "skill"
    return True, f"{name} adında yeni {kind} yarattım Doktor. Şu konularda otomatik devreye girecek: {sample}."
