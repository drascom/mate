"""macOS LaunchAgent backend.

`~/Library/LaunchAgents/com.mate.core.<id>.plist` yazar, `launchctl bootstrap
gui/$UID` ile yükler. Tetiklendiğinde curl ile `/agent/tick?job=<id>` çağırır.
"""
from __future__ import annotations

import asyncio
import os
import plistlib
import shutil
from pathlib import Path

from core import config
from scheduler.base import Job, parse_interval_schedule

LABEL_PREFIX = "com.mate.core."


def _plist_path(job_id: str) -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{LABEL_PREFIX}{job_id}.plist"


def _log_paths(job_id: str) -> tuple[Path, Path]:
    base = config.STATE_DIR / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{job_id}.out", base / f"{job_id}.err"


def _build_plist(job: Job) -> dict:
    interval = parse_interval_schedule(job.schedule) or 60
    out_log, err_log = _log_paths(job.id)
    curl = shutil.which("curl") or "/usr/bin/curl"
    tick_url = f"http://127.0.0.1:{config.PORT}/agent/tick?job={job.id}"
    return {
        "Label": f"{LABEL_PREFIX}{job.id}",
        "ProgramArguments": [curl, "-fsS", "-m", "30", "-X", "POST", tick_url],
        "StartInterval": interval,
        "RunAtLoad": False,
        "StandardOutPath": str(out_log),
        "StandardErrorPath": str(err_log),
    }


class LaunchdScheduler:
    async def create(self, job: Job) -> None:
        path = _plist_path(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump(_build_plist(job), f)
        # Önce varsa eski bootstrap'i sök
        await self.remove(job.id, plist_keep=True)
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "bootstrap", f"gui/{os.getuid()}", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap failed: {stderr.decode()[:200]}")

    async def remove(self, job_id: str, *, plist_keep: bool = False) -> bool:
        label = f"{LABEL_PREFIX}{job_id}"
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "bootout", f"gui/{os.getuid()}/{label}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # bootout missing job için non-zero döner, sessizce yut
        if not plist_keep:
            p = _plist_path(job_id)
            if p.exists():
                p.unlink()
        return True

    async def is_installed(self, job_id: str) -> bool:
        label = f"{LABEL_PREFIX}{job_id}"
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "list", label,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    async def trigger_now(self, job_id: str) -> bool:
        label = f"{LABEL_PREFIX}{job_id}"
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "kickstart", f"gui/{os.getuid()}/{label}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        return proc.returncode == 0
