"""Mate Core — /agent/* endpoint'leri: scheduled job tick + panel için job
list/remove operasyonları. Otonom watcher zaten ayrı çalışıyor; bu modül
sadece dış tetikleyici (launchd/systemd → curl) ve panel interaktif
butonları için.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from autonomous import dispatcher
from core import events
from scheduler import base as sched_base
from scheduler.factory import get_scheduler

router = APIRouter()


@router.post("/agent/tick")
async def agent_tick(job: str = Query(...)) -> dict:
    """launchd/systemd timer bunu çağırır. Job metadata yüklenir, embedded
    action dispatcher üzerinden çalıştırılır, sonuç metadataya yazılır."""
    j = sched_base.load_job(job)
    if not j:
        events.add_event(
            kind="job", status="error", agent="scheduler", session=job,
            text=f"tick {job}", error="job metadata bulunamadı",
        )
        raise HTTPException(404, f"job not found: {job}")
    if not j.enabled:
        return {"status": "skipped", "reason": "disabled"}

    started_at = sched_base.now_iso()
    result = await dispatcher.execute_action(j.action, allowed=j.allowed_actions)
    status = result.get("status", "error")
    summary_bits = []
    if "returncode" in result:
        summary_bits.append(f"rc={result['returncode']}")
    if "http_status" in result:
        summary_bits.append(f"http={result['http_status']}")
    if "error" in result:
        summary_bits.append(f"err={result['error'][:80]}")
    summary = " ".join(summary_bits) or status
    j.last_run = started_at
    j.last_status = status
    j.last_summary = summary
    j.runs += 1
    sched_base.save_job(j)
    events.add_event(
        kind="job", status="ok" if status == "ok" else "error",
        agent="scheduler", session=job,
        text=f"tick {job} ({j.action.get('type')})",
        reply=summary, elapsed_ms=int((result.get("elapsed_s") or 0) * 1000),
        error=result.get("error") if status != "ok" else None,
    )
    return {"status": status, "summary": summary}


@router.get("/agent/jobs")
async def list_agent_jobs() -> dict:
    jobs = sched_base.list_jobs()
    scheduler = get_scheduler()
    out = []
    for j in jobs:
        try:
            installed = await scheduler.is_installed(j.id)
        except Exception:
            installed = False
        out.append({
            "id": j.id,
            "schedule": j.schedule,
            "description": j.description,
            "enabled": j.enabled,
            "installed": installed,
            "action_type": j.action.get("type"),
            "runs": j.runs,
            "last_run": j.last_run,
            "last_status": j.last_status,
            "last_summary": j.last_summary,
            "created_at": j.created_at,
        })
    return {"jobs": out}


@router.post("/agent/jobs/{job_id}/run")
async def run_agent_job_now(job_id: str) -> dict:
    """Manuel olarak job'u şimdi tetikle (panel butonu)."""
    j = sched_base.load_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    result = await dispatcher.execute_action(j.action, allowed=j.allowed_actions)
    j.last_run = sched_base.now_iso()
    j.last_status = result.get("status", "error")
    j.last_summary = result.get("error") or result.get("status", "")[:200]
    j.runs += 1
    sched_base.save_job(j)
    events.add_event(
        kind="job", status="ok" if j.last_status == "ok" else "error",
        agent="scheduler", session=job_id,
        text=f"manual run {job_id}", reply=j.last_summary or "",
    )
    return {"status": j.last_status, "summary": j.last_summary}


@router.delete("/agent/jobs/{job_id}")
async def remove_agent_job(job_id: str) -> dict:
    j = sched_base.load_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    await get_scheduler().remove(job_id)
    sched_base.remove_job_metadata(job_id)
    events.add_event(
        kind="job", status="ok", agent="scheduler", session=job_id,
        text=f"remove {job_id}", reply="kaldırıldı",
    )
    return {"status": "ok"}


@router.post("/agent/jobs/{job_id}/disable")
async def disable_agent_job(job_id: str) -> dict:
    """Job'u launchd/systemd'den çıkar ama metadata'yı koru — sonra
    /enable ile geri başlatılabilir."""
    j = sched_base.load_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    try:
        await get_scheduler().remove(job_id)
    except Exception as exc:
        # bootout fail edebilir (zaten kayıtlı değilse); sessizce devam
        pass
    j.enabled = False
    sched_base.save_job(j)
    events.add_event(
        kind="job", status="ok", agent="scheduler", session=job_id,
        text=f"disable {job_id}", reply="durduruldu",
    )
    return {"status": "ok", "enabled": False}


@router.post("/agent/jobs/{job_id}/enable")
async def enable_agent_job(job_id: str) -> dict:
    """Durdurulmuş job'u yeniden kur."""
    j = sched_base.load_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    j.enabled = True
    sched_base.save_job(j)
    try:
        await get_scheduler().create(j)
    except Exception as exc:
        j.enabled = False
        sched_base.save_job(j)
        raise HTTPException(500, f"scheduler.create failed: {exc}")
    events.add_event(
        kind="job", status="ok", agent="scheduler", session=job_id,
        text=f"enable {job_id}", reply="başlatıldı",
    )
    return {"status": "ok", "enabled": True}
