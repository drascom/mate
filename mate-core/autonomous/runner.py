"""Mate Core — task lifecycle: inbox → processing → done/failed.

Bir task .md geldiğinde:
  1. Frontmatter + body parse et
  2. inbox/ → processing/ taşı, status='processing' yaz
  3. Pi'yi task-runner persona'sıyla çağır (no-tools, JSON output bekleniyor)
  4. dispatcher.parse_action_plan + execute_plan
  5. Sonuç frontmatter'a + body'ye result section yaz, done/ veya failed/ taşı
  6. Her aşamada event log
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from autonomous import dispatcher, frontmatter
from core import config, events
from pi import caller

_DEFAULT_ALLOWED = ["write_file", "run_bash", "http_call", "send_notification"]
_AUTONOMOUS_TIMEOUT_SEC = 120


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


async def process_task(path: Path) -> None:
    """Tek bir task dosyasını işle. Hatalar event'e + failed/ klasörüne gider."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return  # başkası taşımış olabilir

    fm, body = frontmatter.parse(text)
    task_id = str(fm.get("id") or path.stem)
    # Pi --session sadece var olan session'u resume eder; her task tek atış
    # yeni session ile çalışır (gerekirse frontmatter'da pi_session_file
    # saklarız ileride). session_id event log'unda task etiketi olarak görünür.
    pi_session: str | None = None
    session_id = f"task-{task_id}"
    allowed = fm.get("allowed_actions") or _DEFAULT_ALLOWED
    if not isinstance(allowed, list):
        allowed = _DEFAULT_ALLOWED

    # processing/ taşıma
    processing_path = config.TASKS_DIR / "processing" / path.name
    try:
        path.rename(processing_path)
    except FileNotFoundError:
        return
    fm["status"] = "processing"
    fm["started_at"] = _now_iso()
    processing_path.write_text(frontmatter.render(fm, body), encoding="utf-8")

    summary_text = body.strip().splitlines()[0] if body.strip() else f"task {task_id}"
    events.add_event(
        kind="task", status="ok", agent="task-runner", session=session_id,
        text=f"[{task_id}] {summary_text[:80]}",
        reply="görev işleniyor", pending=True,
    )

    # Pi çağrısı — no-tools, JSON output beklenir
    prompt = (
        f"İzinli aksiyon tipleri: {', '.join(allowed)}\n\n"
        f"Görev:\n{body.strip()}"
    )
    started = time.monotonic()
    try:
        reply, elapsed = await caller.call_pi(
            prompt,
            agent_name="task-runner",
            session_id=pi_session,
            tools=None,  # JSON döndürmek için no-tools yeterli; aksiyonu biz yürütüyoruz
            timeout_sec=_AUTONOMOUS_TIMEOUT_SEC,
        )
    except caller.PiTimeout:
        elapsed = time.monotonic() - started
        await _move_failed(processing_path, fm, body, error="pi timeout",
                           task_id=task_id, session_id=session_id,
                           text=summary_text, elapsed_ms=int(elapsed * 1000))
        return
    except caller.PiError as exc:
        elapsed = time.monotonic() - started
        await _move_failed(processing_path, fm, body,
                           error=f"pi exit={exc.returncode}: {exc.stderr[:200]}",
                           task_id=task_id, session_id=session_id,
                           text=summary_text, elapsed_ms=int(elapsed * 1000))
        return

    # JSON action plan parse
    plan = dispatcher.parse_action_plan(reply)
    if plan is None:
        await _move_failed(processing_path, fm, body,
                           error="Pi geçerli JSON action plan döndürmedi",
                           pi_raw=reply,
                           task_id=task_id, session_id=session_id,
                           text=summary_text, elapsed_ms=int(elapsed * 1000))
        return

    # Sırayla yürüt — admin flag task frontmatter'dan geliyor
    admin_flag = bool(fm.get("admin"))
    results = await dispatcher.execute_plan(plan, allowed=allowed, admin=admin_flag)
    any_error = any(r["result"].get("status") in ("error", "rejected") for r in results)

    fm["status"] = "failed" if any_error else "done"
    fm["finished_at"] = _now_iso()
    fm["elapsed_s"] = round(elapsed, 2)
    enriched_body = frontmatter.append_result_section(
        body,
        "Plan",
        plan.get("plan", "(plan yok)"),
    )
    enriched_body = frontmatter.append_result_section(
        enriched_body,
        "Summary",
        plan.get("summary", "(summary yok)"),
    )
    enriched_body = frontmatter.append_result_section(
        enriched_body,
        "Actions",
        "```json\n" + json.dumps(results, ensure_ascii=False, indent=2) + "\n```",
    )

    target_dir = config.TASKS_DIR / ("failed" if any_error else "done")
    target_path = target_dir / processing_path.name
    target_path.write_text(frontmatter.render(fm, enriched_body), encoding="utf-8")
    processing_path.unlink(missing_ok=True)

    # Pending event'i güncelle
    if not events.update_pending_event(f"[{task_id}] {summary_text[:80]}", {
        "status": "error" if any_error else "ok",
        "agent": "task-runner",
        "session": session_id,
        "elapsed_ms": int(elapsed * 1000),
        "reply": plan.get("summary") or "",
        "error": "bir veya birden çok aksiyon hatalı" if any_error else None,
    }, kind="task"):
        events.add_event(
            kind="task", status="error" if any_error else "ok",
            agent="task-runner", session=session_id,
            text=f"[{task_id}] {summary_text[:80]}",
            reply=plan.get("summary") or "",
            elapsed_ms=int(elapsed * 1000),
            error="bir veya birden çok aksiyon hatalı" if any_error else None,
        )


async def _move_failed(
    processing_path: Path,
    fm: dict,
    body: str,
    *,
    error: str,
    task_id: str,
    session_id: str,
    text: str,
    elapsed_ms: int,
    pi_raw: str | None = None,
) -> None:
    fm["status"] = "failed"
    fm["finished_at"] = _now_iso()
    fm["error"] = error[:300]
    fm["retry_count"] = int(fm.get("retry_count") or 0)
    enriched = frontmatter.append_result_section(body, "Error", error)
    if pi_raw:
        enriched = frontmatter.append_result_section(enriched, "Pi raw output", pi_raw)
    target = config.TASKS_DIR / "failed" / processing_path.name
    target.write_text(frontmatter.render(fm, enriched), encoding="utf-8")
    processing_path.unlink(missing_ok=True)
    if not events.update_pending_event(f"[{task_id}] {text[:80]}", {
        "status": "error", "agent": "task-runner", "session": session_id,
        "elapsed_ms": elapsed_ms, "error": error[:200], "reply": "",
    }, kind="task"):
        events.add_event(
            kind="task", status="error", agent="task-runner", session=session_id,
            text=f"[{task_id}] {text[:80]}", error=error[:200], elapsed_ms=elapsed_ms,
        )


async def worker_loop(queue: asyncio.Queue) -> None:
    """Tek worker, sıralı. MVP için yeterli; ileride sayı arttırılabilir."""
    while True:
        path: Path = await queue.get()
        try:
            await process_task(path)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[autonomous] worker error on {path.name}: {exc}", flush=True)
