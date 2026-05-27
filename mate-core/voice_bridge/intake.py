"""Mate Core — voice-intake JSON parse + pending task lifecycle.

voice-intake persona Pi'den JSON döner. Bu modül:
  - JSON bloğunu parse + validate eder
  - Pending dosyayı tasks/pending/<id>.md olarak yazar
  - Onay → tasks/inbox/<id>.md taşır (otonom runner devralır)
  - İptal → pending dosyasını siler
  - Onaylanan task'ı session sidecar'a kaydeder (sayfa yenilemede chat'te
    sonuç kartı pozisyonu korunsun diye)
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from autonomous import frontmatter
from core import config

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)
_VALID_INTENTS = {"chat", "task", "confirm", "cancel"}
_VALID_ACTIONS = {
    "write_file", "run_bash", "http_call", "schedule_job",
    "send_notification", "agentic_pi",
}
_SAFE_ID_RE = re.compile(r"[^a-z0-9_\-]")


def pending_dir() -> Path:
    p = config.TASKS_DIR / "pending"
    p.mkdir(parents=True, exist_ok=True)
    return p


def inbox_dir() -> Path:
    p = config.TASKS_DIR / "inbox"
    p.mkdir(parents=True, exist_ok=True)
    return p


def parse_intake_json(reply: str) -> dict | None:
    """Pi cevabından JSON çıkar ve şemayı doğrula. Geçersizse None.

    Şema:
      intent: "chat"|"task"|"confirm"|"cancel"
      tts_reply: str
      draft_task (sadece intent=task): {id, title, allowed_actions, body}
    """
    m = _JSON_BLOCK_RE.search(reply)
    candidate = m.group(1) if m else reply.strip()
    candidate = candidate.strip()
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return None
    try:
        obj = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    intent = obj.get("intent")
    if intent not in _VALID_INTENTS:
        return None
    if not isinstance(obj.get("tts_reply"), str) or not obj["tts_reply"].strip():
        return None
    if intent == "task":
        draft = obj.get("draft_task")
        if not isinstance(draft, dict):
            return None
        if not isinstance(draft.get("id"), str) or not draft["id"].strip():
            return None
        if not isinstance(draft.get("body"), str) or not draft["body"].strip():
            return None
        actions = draft.get("allowed_actions")
        if not isinstance(actions, list) or not actions:
            return None
        if not all(isinstance(a, str) and a in _VALID_ACTIONS for a in actions):
            return None
    return obj


def _safe_id(raw: str) -> str:
    safe = _SAFE_ID_RE.sub("", raw.lower().strip())
    return safe or datetime.utcnow().strftime("task-%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def write_pending_task(draft: dict, *, source: str = "user", admin: bool = False) -> dict:
    """Pending dosyasını diske yaz. Aynı id varsa timestamp eklenir.

    admin=True → frontmatter.admin=true yazılır; dispatcher agentic_pi
    aksiyonuna sadece bu task'larda izin verir.
    """
    task_id = _safe_id(draft["id"])
    path = pending_dir() / f"{task_id}.md"
    if path.exists():
        task_id = f"{task_id}-{datetime.utcnow().strftime('%H%M%S')}"
        path = pending_dir() / f"{task_id}.md"

    title = draft.get("title", "").strip() or task_id
    actions = draft.get("allowed_actions", [])
    fm = {
        "id": task_id,
        "source": source,
        "created": _now_iso(),
        "status": "pending",
        "title": title,
        "allowed_actions": actions,
        "priority": "normal",
    }
    if admin:
        fm["admin"] = True
    body = draft["body"].rstrip() + "\n"
    path.write_text(frontmatter.render(fm, body), encoding="utf-8")
    return {
        "id": task_id,
        "title": title,
        "allowed_actions": actions,
        "admin": admin,
        "body_preview": body.strip()[:240],
        "created": fm["created"],
        "file": path.name,
    }


def move_pending_to_inbox(task_id: str) -> bool:
    src = pending_dir() / f"{task_id}.md"
    if not src.exists():
        return False
    dst = inbox_dir() / src.name
    src.rename(dst)
    return True


def delete_pending(task_id: str) -> bool:
    src = pending_dir() / f"{task_id}.md"
    if not src.exists():
        return False
    src.unlink()
    return True


def list_pending() -> list[dict]:
    out: list[dict] = []
    for p in sorted(pending_dir().glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
            fm, body = frontmatter.parse(text)
        except Exception:
            continue
        out.append({
            "id": fm.get("id") or p.stem,
            "title": fm.get("title", ""),
            "created": fm.get("created"),
            "allowed_actions": fm.get("allowed_actions") or [],
            "admin": bool(fm.get("admin")),
            "body_preview": body.strip()[:240],
            "file": p.name,
        })
    return out


def recover_pending_state() -> dict | None:
    """Bridge restart sonrası: pending/ klasöründe dosya varsa en yenisini
    aktif draft olarak geri yükle (in-memory state recovery)."""
    items = list_pending()
    if not items:
        return None
    # Created'a göre son yazılan ilk taraf
    items.sort(key=lambda x: x.get("created") or "", reverse=True)
    return items[0]


def _find_task_file(task_id: str) -> tuple[Path, str] | None:
    """task_id'yi inbox/processing/done/failed klasörlerinde ara."""
    safe = _safe_id(task_id)
    for subdir in ("processing", "done", "failed", "inbox"):
        p = config.TASKS_DIR / subdir / f"{safe}.md"
        if p.exists():
            return p, subdir
    return None


_SECTION_RE = re.compile(r"^##\s+(?P<head>[^\n]+)\n(?P<body>.*?)(?=\n##\s+|\Z)", re.DOTALL | re.MULTILINE)
_JSON_BLOCK_GREEDY_RE = re.compile(r"```(?:json)?\s*\n(.*)\n```", re.DOTALL)


def _extract_sections(body: str) -> dict[str, str]:
    """Body içindeki `## Heading` bloklarını dict'e topla."""
    out: dict[str, str] = {}
    for m in _SECTION_RE.finditer(body):
        out[m.group("head").strip()] = m.group("body").strip()
    return out


def _parse_actions_json(actions_section: str) -> list[dict]:
    m = _JSON_BLOCK_GREEDY_RE.search(actions_section)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []
    return data if isinstance(data, list) else []


# ---------- session sidecar: onaylanmış görevlerin chat'te kalıcılığı ----------
#
# Pi session jsonl'a kendi entry'lerimizi yazmıyoruz çünkü o dosyanın formatı
# Pi'ye ait ve `--session` resume edilirken context'i bozabilir. Bunun yerine
# state/chat_tasks.json bir sidecar tutar:
#   {"<session_id>": [{"task_id":..., "after_message_count": N, "ts":...}, ...]}

_CHAT_TASKS_FILE = config.STATE_DIR / "chat_tasks.json"
_chat_tasks_lock = threading.Lock()


def _load_chat_tasks() -> dict[str, list[dict]]:
    if not _CHAT_TASKS_FILE.exists():
        return {}
    try:
        data = json.loads(_CHAT_TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_chat_tasks(data: dict) -> None:
    _CHAT_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CHAT_TASKS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _CHAT_TASKS_FILE)


def record_session_task(session_id: str, task_id: str, after_message_count: int) -> None:
    """Bir chat session'ı için onaylanmış task'ı sidecar'a yaz."""
    if not session_id or not task_id:
        return
    with _chat_tasks_lock:
        data = _load_chat_tasks()
        entries = data.get(session_id) or []
        if any(e.get("task_id") == task_id for e in entries):
            return  # idempotent — aynı task'ı tekrar ekleme
        entries.append({
            "task_id": task_id,
            "after_message_count": int(after_message_count),
            "ts": _now_iso(),
        })
        data[session_id] = entries
        _save_chat_tasks(data)


def enriched_session_tasks(session_id: str) -> list[dict]:
    """Session'ın task referanslarını + güncel task_status verisini birleştir.

    Chat UI sayfa yenilenince bu listeyi kullanır; her referans için
    task_status() sonucunu data alanında döner. Task dosyası bulunamazsa
    (silinmiş vs.) atlanır."""
    if not session_id:
        return []
    with _chat_tasks_lock:
        entries = list(_load_chat_tasks().get(session_id) or [])
    out: list[dict] = []
    for e in entries:
        info = task_status(e.get("task_id") or "")
        if not info:
            continue
        out.append({
            "after_message_count": int(e.get("after_message_count") or 0),
            "data": info,
        })
    out.sort(key=lambda x: x["after_message_count"])
    return out


def task_status(task_id: str) -> dict | None:
    """Task dosyasını oku, chat'e dönecek özet dict üret. Bulunamazsa None."""
    found = _find_task_file(task_id)
    if not found:
        return None
    path, subdir = found
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    fm, body = frontmatter.parse(text)
    sections = _extract_sections(body)
    actions_raw = _parse_actions_json(sections.get("Actions", ""))

    action_previews: list[dict] = []
    for entry in actions_raw:
        action = entry.get("action") if isinstance(entry, dict) else {}
        result = entry.get("result") if isinstance(entry, dict) else {}
        if not isinstance(action, dict):
            action = {}
        if not isinstance(result, dict):
            result = {}
        # Önce gerçek çıktı alanlarını dene, sonra hata mesajına düş
        preview = (
            result.get("output")
            or result.get("stdout")
            or result.get("body_preview")
            or result.get("reason")
            or result.get("error")
            or ""
        )
        action_previews.append({
            "type": action.get("type"),
            "status": result.get("status"),
            "preview": (preview or "")[:1000],
            "elapsed_s": result.get("elapsed_s"),
        })

    status = fm.get("status") or subdir
    return {
        "id": fm.get("id") or task_id,
        "title": fm.get("title", "") or task_id,
        "status": status,
        "subdir": subdir,
        "elapsed_s": fm.get("elapsed_s"),
        "started_at": fm.get("started_at"),
        "finished_at": fm.get("finished_at"),
        "error": fm.get("error"),
        "summary": sections.get("Summary", ""),
        "plan": sections.get("Plan", ""),
        "actions": action_previews,
    }
