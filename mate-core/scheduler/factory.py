"""Mate Core — scheduler factory: platform.system() → uygun backend."""
from __future__ import annotations

from core import config
from scheduler.base import Scheduler


def get_scheduler() -> Scheduler:
    if config.SYSTEM == "Darwin":
        from scheduler.launchd import LaunchdScheduler
        return LaunchdScheduler()
    if config.SYSTEM == "Linux":
        from scheduler.systemd import SystemdScheduler
        return SystemdScheduler()
    raise RuntimeError(f"Mate Core unsupported platform: {config.SYSTEM}")
