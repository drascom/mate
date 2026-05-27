"""systemd --user backend (Ubuntu prod).

`~/.config/systemd/user/mate-<id>.{service,timer}` yazıp `systemctl --user
daemon-reload` + `enable --now` çalıştırır. Tetiklendiğinde curl ile
`/agent/tick?job=<id>` çağırır.

Mac üzerinde test edilmedi — Faz 5 Ubuntu hedefli olduğunda doğrulanır.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from core import config
from scheduler.base import Job, parse_interval_schedule

UNIT_PREFIX = "mate-"


def _unit_dir() -> Path:
    d = Path.home() / ".config/systemd/user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _service_path(job_id: str) -> Path:
    return _unit_dir() / f"{UNIT_PREFIX}{job_id}.service"


def _timer_path(job_id: str) -> Path:
    return _unit_dir() / f"{UNIT_PREFIX}{job_id}.timer"


def _format_oncalendar(seconds: int) -> str:
    """N saniyelik interval'i OnUnitActiveSec olarak verir; tutarlı olduğu için
    OnCalendar yerine bu kullanılır."""
    return f"{seconds}s"


def _write_units(job: Job) -> None:
    interval = parse_interval_schedule(job.schedule) or 60
    curl = shutil.which("curl") or "/usr/bin/curl"
    tick_url = f"http://127.0.0.1:{config.PORT}/agent/tick?job={job.id}"
    service = f"""[Unit]
Description=Mate Core job {job.id}

[Service]
Type=oneshot
ExecStart={curl} -fsS -m 30 -X POST {tick_url}
"""
    timer = f"""[Unit]
Description=Mate Core timer {job.id}

[Timer]
OnBootSec=30s
OnUnitActiveSec={_format_oncalendar(interval)}
Persistent=true

[Install]
WantedBy=timers.target
"""
    _service_path(job.id).write_text(service, encoding="utf-8")
    _timer_path(job.id).write_text(timer, encoding="utf-8")


async def _systemctl(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    return proc.returncode, stderr.decode("utf-8", errors="replace")


class SystemdScheduler:
    async def create(self, job: Job) -> None:
        _write_units(job)
        await _systemctl("daemon-reload")
        rc, err = await _systemctl("enable", "--now", f"{UNIT_PREFIX}{job.id}.timer")
        if rc != 0:
            raise RuntimeError(f"systemctl enable failed: {err[:200]}")

    async def remove(self, job_id: str) -> bool:
        unit = f"{UNIT_PREFIX}{job_id}.timer"
        await _systemctl("disable", "--now", unit)
        for p in (_service_path(job_id), _timer_path(job_id)):
            if p.exists():
                p.unlink()
        await _systemctl("daemon-reload")
        return True

    async def is_installed(self, job_id: str) -> bool:
        rc, _ = await _systemctl("status", f"{UNIT_PREFIX}{job_id}.timer", "--no-pager")
        return rc == 0

    async def trigger_now(self, job_id: str) -> bool:
        rc, _ = await _systemctl("start", f"{UNIT_PREFIX}{job_id}.service")
        return rc == 0
