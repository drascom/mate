"""Mate Core — task dosyası frontmatter parse/serialize.

Format: voice persona frontmatter'ı ile uyumlu (üç tire + key: value).
Desteklenen tipler:
  - string (default; tırnaklar opsiyonel)
  - integer (yalnız rakam)
  - bool (true/false)
  - null (null/none/~)
  - JSON-flow list ([…]) — items string olarak

Karmaşık nested veri (result/error) frontmatter yerine body'ye Markdown
section olarak eklenir (Result tag'i). Bu sayede insan kolay okur.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Returns (frontmatter dict, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm_text = match.group(1)
    body = text[match.end():]

    fm: dict[str, Any] = {}
    for raw_line in fm_text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        fm[key] = _coerce(value)
    return fm, body


def _coerce(value: str) -> Any:
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items: list[str] = []
        for raw in _split_csv(inner):
            s = raw.strip().strip('"').strip("'")
            items.append(s)
        return items
    low = value.lower()
    if low in ("null", "none", "~"):
        return None
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value.strip('"').strip("'")


def _split_csv(inner: str) -> list[str]:
    """Comma-split honoring quoted strings."""
    out: list[str] = []
    buf: list[str] = []
    in_q: str | None = None
    for ch in inner:
        if in_q:
            buf.append(ch)
            if ch == in_q:
                in_q = None
        elif ch in ("'", '"'):
            in_q = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def render(fm: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {_format_value(v)}")
    lines.append("---")
    lines.append("")
    lines.append(body.lstrip("\n"))
    return "\n".join(lines)


def _format_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        items = ", ".join(json.dumps(x, ensure_ascii=False) for x in v)
        return f"[{items}]"
    # default string — no quotes (frontmatter style)
    s = str(v)
    if "\n" in s or s.startswith("-") or ":" in s:
        return json.dumps(s, ensure_ascii=False)
    return s


def append_result_section(body: str, heading: str, content: str) -> str:
    """Body'ye Markdown section ekle. Önceki aynı heading varsa altına yazar."""
    body = body.rstrip()
    if body:
        body += "\n\n"
    body += f"## {heading}\n\n{content.rstrip()}\n"
    return body
