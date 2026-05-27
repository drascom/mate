"""Mate Core — paylaşılan event log + SSE pipe.

Voice, otonom runner, scheduler, panel hepsi `add_event()` üzerinden aynı
deque'ya yazar; `/events/stream` SSE bağlı tüm istemcilere push eder.
Bridge restart edilince in-memory history sıfırlanır — bu kabul edilebilir,
ileride persistent log gerekirse jsonl dosyasına da yazılabilir.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime
from typing import Any

_events: deque[dict[str, Any]] = deque(maxlen=200)
_event_subscribers: set[asyncio.Queue] = set()


def _notify_subscribers() -> None:
    for queue in list(_event_subscribers):
        try:
            queue.put_nowait(True)
        except asyncio.QueueFull:
            pass


def add_event(
    *,
    kind: str,
    status: str = "ok",
    agent: str | None = None,
    session: str | None = None,
    text: str = "",
    reply: str | None = None,
    error: str | None = None,
    elapsed_ms: int = 0,
    pending: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Yeni event ekle ve SSE subscribers'a haber ver.

    `kind`: 'conversation' | 'task' | 'job' | 'reset' | 'http' | …
    `pending`: True ise sonradan `update_pending_event` ile aynı kayda eklenir.
    """
    item: dict[str, Any] = {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "kind": kind,
        "status": status,
        "agent": agent,
        "session": session,
        "elapsed_ms": elapsed_ms,
        "text": text,
        "reply": reply or "",
        "error": error,
        "pending": pending,
    }
    if extra:
        item.update(extra)
    _events.appendleft(item)
    _notify_subscribers()
    return item


def update_pending_event(text: str, updates: dict[str, Any], kind: str = "conversation") -> bool:
    """Bekleyen STT transcript event'ini bridge cevabı/hatasıyla güncelle.

    Match: aynı kind ve text. Bulunursa pending=False, updates merge edilir
    ve subscribers tetiklenir.
    """
    for event in _events:
        if event.get("kind") == kind and event.get("pending") is True and event.get("text") == text:
            event.update(updates)
            event["pending"] = False
            _notify_subscribers()
            return True
    return False


def all_events() -> list[dict[str, Any]]:
    return list(_events)


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    _event_subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _event_subscribers.discard(queue)


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
