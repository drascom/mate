"""Mate Core — scheduler protocol ve job metadata storage.

Job şeması: launchd/systemd asıl tetiklemeyi yapar, action body Mate
state_dir/jobs/<id>.json'da durur. Tetiklendiğinde launchd/systemd
`POST /agent/tick?job=<id>` çağırır; /agent/tick dispatcher'a verir.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from core import config


@dataclass
class Job:
    id: str
    schedule: str               # "every:Nm" | "every:Nh" | "every:Ns"
    action: dict[str, Any]      # tek bir HANDLERS action spec'i
    description: str = ""
    allowed_actions: list[str] = field(default_factory=list)
    enabled: bool = True
    created_at: str = ""
    last_run: str | None = None
    last_status: str | None = None
    last_summary: str | None = None
    runs: int = 0


def jobs_dir() -> Path:
    d = config.STATE_DIR / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def save_job(job: Job) -> None:
    job_path(job.id).write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(job_id: str) -> Job | None:
    p = job_path(job_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return Job(**data)


def list_jobs() -> list[Job]:
    out: list[Job] = []
    for p in sorted(jobs_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(Job(**data))
        except Exception:
            continue
    return out


def remove_job_metadata(job_id: str) -> bool:
    p = job_path(job_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def parse_interval_schedule(schedule: str) -> int | None:
    """`every:Nm`/`every:Nh`/`every:Ns` → saniye. Diğer formatlar None."""
    if not schedule.startswith("every:"):
        return None
    rest = schedule[6:].strip()
    if not rest:
        return None
    unit = rest[-1].lower()
    value_part = rest[:-1]
    try:
        value = int(value_part)
    except ValueError:
        return None
    if value <= 0:
        return None
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    mul = multipliers.get(unit)
    if mul is None:
        return None
    return value * mul


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class Scheduler(Protocol):
    """Platform-specific job lifecycle."""

    async def create(self, job: Job) -> None: ...
    async def remove(self, job_id: str) -> bool: ...
    async def is_installed(self, job_id: str) -> bool: ...
    async def trigger_now(self, job_id: str) -> bool: ...
