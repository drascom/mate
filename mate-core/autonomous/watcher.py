"""Mate Core — `tasks/inbox/` event-triggered watcher.

watchfiles.awatch async generator → asyncio.Queue → runner worker.
Startup'ta inbox'taki mevcut .md dosyaları da kuyruğa alınır (process restart
sırasında biriken görevler kaybolmasın).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from watchfiles import Change, awatch

from autonomous import runner
from core import config


def _is_task_file(path_str: str) -> bool:
    p = Path(path_str)
    if p.suffix != ".md":
        return False
    name = p.name
    return not (name.startswith(".") or name.endswith(".swp") or name.endswith("~"))


async def run() -> None:
    """Lifespan task: ölünceye kadar inbox'ı izle, runner worker'a feed et."""
    inbox = config.TASKS_DIR / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    queue: asyncio.Queue = asyncio.Queue()

    # Restart-resilience: zaten inbox'ta bekleyen dosyaları kuyruğa al
    for existing in sorted(inbox.glob("*.md")):
        if _is_task_file(str(existing)):
            await queue.put(existing)

    worker_task = asyncio.create_task(runner.worker_loop(queue))
    try:
        async for changes in awatch(str(inbox), debounce=300):
            for change_type, file_path in changes:
                if change_type not in (Change.added, Change.modified):
                    continue
                if not _is_task_file(file_path):
                    continue
                # modified: aynı path tekrar kuyruğa girmesin diye basit dedupe yok
                # (MVP); runner zaten dosya yoksa sessizce dönüyor.
                await queue.put(Path(file_path))
    except asyncio.CancelledError:
        worker_task.cancel()
        try:
            await worker_task
        except (asyncio.CancelledError, Exception):
            pass
        raise
