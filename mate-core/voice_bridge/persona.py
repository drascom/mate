"""Mate Core — voice persona seçimi (frontmatter trigger eşleşmesi).

Bridge her /chat çağrısında trigger map'i taze okur; runtime'da yaratılan yeni
persona'lar (agent-builder ile) hemen aktif olur.
"""
from __future__ import annotations

import re
from pathlib import Path

from core import config

# Frontmatter parser — basit JSON-flow YAML:
#   ---
#   triggers: ["foo", "bar"]
#   ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_TRIGGERS_RE = re.compile(r'^triggers:\s*\[(.*?)\]\s*$', re.MULTILINE | re.DOTALL)
_STRING_ITEM_RE = re.compile(r'"([^"]+)"')


def parse_agent_triggers(md_path: Path) -> list[str]:
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return []
    fm_match = _FRONTMATTER_RE.match(text)
    if not fm_match:
        return []
    fm = fm_match.group(1)
    tr_match = _TRIGGERS_RE.search(fm)
    if not tr_match:
        return []
    return [s.lower() for s in _STRING_ITEM_RE.findall(tr_match.group(1))]


def load_trigger_map() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not config.AGENTS_DIR.exists():
        return result
    for md in sorted(config.AGENTS_DIR.glob("*.md")):
        name = md.stem
        triggers = parse_agent_triggers(md)
        if triggers:
            result[name] = triggers
    return result


def select_agent(text: str) -> str:
    """Gelen text'te trigger eşleşmesi bulursa o persona'yı döndürür.
    agent-builder'a öncelik ver — "yeni tarif" gibi belirsiz frase başka
    persona ile karışmasın. Hiç match yoksa DEFAULT_AGENT (voice-default)."""
    lower = text.lower()
    trigger_map = load_trigger_map()
    if "agent-builder" in trigger_map:
        if any(kw in lower for kw in trigger_map["agent-builder"]):
            return "agent-builder"
    for name, triggers in trigger_map.items():
        if name == "agent-builder":
            continue
        if any(kw in lower for kw in triggers):
            return name
    return config.DEFAULT_AGENT
