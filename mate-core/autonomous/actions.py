"""Mate Core — otonom dispatcher tarafından yürütülen aksiyon handler'ları.

Pi JSON döner, dispatcher action listesinde tek tek bu fonksiyonları çağırır.
Her handler `dict` action spec'i alır, `dict` result döner (status, output, error).
"""
from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core import config

# write_file safety: yıkıcı yollara izin verme. Liste kısa tutuldu; Pi'nin
# kazara /etc'e yazmasını engeller, kullanıcı bilinçli olarak ayrı tip
# eklemek isterse persona/dispatcher seviyesinde gevşetilir.
_FORBIDDEN_WRITE_PREFIXES = ("/etc", "/System", "/Library/LaunchDaemons", "/usr", "/bin", "/sbin", "/var/db")
# run_bash safety: tek satır içinde geçen yıkıcı kalıplar reddedilir.
_FORBIDDEN_BASH_PATTERNS = ("rm -rf /", "mkfs", "dd if=", "> /dev/sda", "chmod -R 000 /")
_DEFAULT_BASH_TIMEOUT = 30
_MAX_BASH_TIMEOUT = 300


class ActionError(Exception):
    pass


async def write_file(spec: dict[str, Any]) -> dict[str, Any]:
    path_str = spec.get("path")
    content = spec.get("content", "")
    if not isinstance(path_str, str) or not path_str:
        raise ActionError("path zorunlu")
    if not isinstance(content, str):
        raise ActionError("content string olmalı")
    target = Path(path_str)
    if not target.is_absolute():
        raise ActionError("path mutlak olmalı")
    for forb in _FORBIDDEN_WRITE_PREFIXES:
        if path_str.startswith(forb):
            raise ActionError(f"sistem dizinine yazma yasak: {forb}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    mode = spec.get("mode")
    if isinstance(mode, int):
        target.chmod(mode)
    elif isinstance(mode, str) and mode.startswith("0"):
        try:
            target.chmod(int(mode, 8))
        except ValueError:
            pass
    return {"status": "ok", "path": str(target), "bytes": len(content.encode("utf-8"))}


async def run_bash(spec: dict[str, Any]) -> dict[str, Any]:
    command = spec.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ActionError("command zorunlu")
    for forb in _FORBIDDEN_BASH_PATTERNS:
        if forb in command:
            raise ActionError(f"yasak desen: {forb}")
    timeout = spec.get("timeout_sec", _DEFAULT_BASH_TIMEOUT)
    try:
        timeout = max(1, min(int(timeout), _MAX_BASH_TIMEOUT))
    except (TypeError, ValueError):
        timeout = _DEFAULT_BASH_TIMEOUT
    cwd = spec.get("cwd") or None
    started = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {
            "status": "error",
            "error": f"timeout {timeout}s",
            "elapsed_s": time.monotonic() - started,
        }
    elapsed = time.monotonic() - started
    return {
        "status": "ok" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-1000:],
        "elapsed_s": elapsed,
    }


async def http_call(spec: dict[str, Any]) -> dict[str, Any]:
    method = (spec.get("method") or "GET").upper()
    url = spec.get("url")
    if not isinstance(url, str) or not url:
        raise ActionError("url zorunlu")
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
        raise ActionError(f"method desteklenmiyor: {method}")
    headers = spec.get("headers") or {}
    body_obj = spec.get("body")
    data: bytes | None = None
    if body_obj is not None:
        if isinstance(body_obj, (dict, list)):
            data = json.dumps(body_obj).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(body_obj, str):
            data = body_obj.encode("utf-8")
        else:
            raise ActionError("body string veya JSON serializable olmalı")

    def _do() -> dict[str, Any]:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read(64 * 1024).decode("utf-8", errors="replace")
                return {
                    "status": "ok",
                    "http_status": resp.status,
                    "elapsed_s": time.monotonic() - started,
                    "body_preview": body[:4000],
                }
        except urllib.error.HTTPError as exc:
            return {
                "status": "error",
                "http_status": exc.code,
                "error": str(exc),
                "elapsed_s": time.monotonic() - started,
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc)[:300],
                "elapsed_s": time.monotonic() - started,
            }

    return await asyncio.to_thread(_do)


async def send_notification(spec: dict[str, Any]) -> dict[str, Any]:
    title = spec.get("title") or "Mate"
    body = spec.get("body") or ""
    if config.SYSTEM == "Darwin":
        # osascript display notification kabuğa shell-out. ensure_ascii=False
        # çünkü AppleScript `\uXXXX` escape'ini parse etmiyor; UTF-8 bytes
        # doğrudan geçer. json.dumps inner quote'ları zaten `\"` yapıyor.
        body_q = json.dumps(body, ensure_ascii=False)
        title_q = json.dumps(title, ensure_ascii=False)
        cmd = [
            "osascript",
            "-e",
            f'display notification {body_q} with title {title_q}',
        ]
    else:
        # Ubuntu: notify-send (varsa)
        if not shutil.which("notify-send"):
            return {"status": "error", "error": "notify-send bulunamadı"}
        cmd = ["notify-send", title, body]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        return {"status": "error", "error": stderr.decode("utf-8", errors="replace")[:200]}
    return {"status": "ok"}


_DEFAULT_AGENTIC_TOOLS = ["bash", "read", "write", "edit", "grep", "find", "ls"]
_AGENTIC_TIMEOUT_SEC = 300
_AGENTIC_MAX_TIMEOUT_SEC = 900


async def agentic_pi(spec: dict[str, Any]) -> dict[str, Any]:
    """Pi'yi tam tool yetkisiyle çağır — admin context'te.

    Beklenen şema:
      {type: agentic_pi, goal: "<doğal dil hedef>", tools?: [...], cwd?: str,
       timeout_sec?: int}

    Tool whitelist default'u read/write/edit/grep/find/ls/bash — Pi proje
    içinde refactor/edit/debug yapabilsin diye. Admin gate dispatcher
    seviyesinde (task fm.admin=True şartı).
    """
    from pi import caller  # geç import: aksiyon modülü Pi'ye bağımlı görünmesin

    goal = spec.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ActionError("goal zorunlu (doğal dil hedef)")

    tools = spec.get("tools")
    if tools is None:
        tools = list(_DEFAULT_AGENTIC_TOOLS)
    elif not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise ActionError("tools listesi string'lerden olmalı")

    cwd_str = spec.get("cwd")
    if cwd_str is not None and not isinstance(cwd_str, str):
        raise ActionError("cwd string olmalı")
    cwd = Path(cwd_str) if cwd_str else config.CORE_DIR

    timeout = spec.get("timeout_sec", _AGENTIC_TIMEOUT_SEC)
    try:
        timeout = max(30, min(int(timeout), _AGENTIC_MAX_TIMEOUT_SEC))
    except (TypeError, ValueError):
        timeout = _AGENTIC_TIMEOUT_SEC

    try:
        out, elapsed = await caller.call_pi(
            goal,
            tools=tools,
            cwd=cwd,
            timeout_sec=timeout,
        )
    except caller.PiTimeout as exc:
        return {"status": "error", "error": str(exc), "elapsed_s": timeout}
    except caller.PiError as exc:
        return {
            "status": "error",
            "error": f"pi exit={exc.returncode}: {exc.stderr[:300]}",
            "elapsed_s": 0,
        }

    return {
        "status": "ok",
        "output": out[:8000],
        "elapsed_s": round(elapsed, 2),
        "tools": tools,
        "cwd": str(cwd),
    }


async def schedule_job(spec: dict[str, Any]) -> dict[str, Any]:
    """Mevcut platforma (launchd/systemd) yeni recurring job kur.

    Beklenen şema:
      {type: schedule_job, job_id: <id>, schedule: "every:Nm", action: <single-action-dict>}
    """
    from scheduler import base as sched_base
    from scheduler.factory import get_scheduler

    job_id = spec.get("job_id")
    schedule = spec.get("schedule")
    action = spec.get("action")
    if not isinstance(job_id, str) or not job_id.replace("-", "").replace("_", "").isalnum():
        raise ActionError("job_id alfanümerik string olmalı (- ve _ izinli)")
    if not isinstance(schedule, str) or sched_base.parse_interval_schedule(schedule) is None:
        raise ActionError("schedule 'every:Nm/Nh/Ns' formatında olmalı")
    if not isinstance(action, dict) or "type" not in action:
        raise ActionError("action tek bir aksiyon dict'i olmalı (type alanı zorunlu)")
    nested_type = action.get("type")
    if nested_type == "schedule_job":
        raise ActionError("nested schedule_job yasak")
    if nested_type not in HANDLERS:
        raise ActionError(f"nested action tipi bilinmiyor: {nested_type}")

    job = sched_base.Job(
        id=job_id,
        schedule=schedule,
        action=action,
        description=spec.get("description") or "",
        allowed_actions=[nested_type],
        created_at=sched_base.now_iso(),
    )
    sched_base.save_job(job)
    try:
        await get_scheduler().create(job)
    except Exception as exc:
        sched_base.remove_job_metadata(job_id)
        raise ActionError(f"scheduler create: {exc}")
    return {"status": "ok", "job_id": job_id, "schedule": schedule, "nested_type": nested_type}


# Tip → handler haritası. Dispatcher buradan resolve eder.
HANDLERS = {
    "write_file": write_file,
    "run_bash": run_bash,
    "http_call": http_call,
    "send_notification": send_notification,
    "schedule_job": schedule_job,
    "agentic_pi": agentic_pi,
}

# Admin gate gerektiren aksiyon tipleri. Dispatcher fm.admin=True şartı arar.
ADMIN_ONLY_ACTIONS = {"agentic_pi"}
