"""Mate Core — voice bridge HTTP endpoint'leri.

iOS app + panel chat bu endpoint'lerden tüketiyor:
  GET  /health
  POST /stt-event {text}                — STT transkript event'i
  POST /chat      {text}                — voice-intake persona + intent routing
  POST /chat/reset                       — session_id'yi sıfırla
  GET  /chat/sessions                    — Pi session listesi
  GET  /chat/history?session=...         — session mesajları
  POST /chat/select {session_id|null}    — aktif session'ı değiştir
  GET  /chat/pending                     — onay bekleyen görev var mı
  POST /chat/confirm-pending             — pending → inbox (panel butonu)
  POST /chat/cancel-pending              — pending'i sil (panel butonu)

`_state["session_id"]`: chat session. `_pending_state["draft"]`: onay bekleyen
görev meta'sı. Bridge restart sonrası pending/ klasöründen recovery yapılır.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from core import auth, config, events
from pi import caller
from voice_bridge import builder, intake, persona

router = APIRouter()

_state: dict = {"session_id": None}
_pending_state: dict = {"draft": None}  # {id, title, allowed_actions, body_preview, created_at}

# Bridge boot'unda diskteki pending varsa state'e geri yükle
_recovered = intake.recover_pending_state()
if _recovered:
    _pending_state["draft"] = {
        "id": _recovered["id"],
        "title": _recovered.get("title") or _recovered["id"],
        "allowed_actions": _recovered.get("allowed_actions") or [],
        "admin": bool(_recovered.get("admin")),
        "body_preview": _recovered.get("body_preview") or "",
        "created_at": _recovered.get("created") or "",
    }
    print(f"[bridge] pending state recovered: {_pending_state['draft']['id']}", flush=True)


class ChatIn(BaseModel):
    text: str
    admin_mode: bool = False  # panel toggle; sadece login admin için geçerli


class STTEventIn(BaseModel):
    text: str


class ChatOut(BaseModel):
    reply: str
    elapsed: float
    session_id: str | None
    intent: str | None = None
    pending_task: dict | None = None


class SelectSessionIn(BaseModel):
    session_id: str | None = None


def _auth(authorization: str | None) -> None:
    return


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "mate-core",
        "session_active": _state["session_id"] is not None,
        "pending_active": _pending_state["draft"] is not None,
    }


@router.post("/stt-event")
async def stt_event(body: STTEventIn, authorization: str | None = Header(default=None)) -> dict:
    _auth(authorization)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    events.add_event(
        kind="conversation",
        status="ok",
        agent=None,
        session=_state["session_id"],
        text=text,
        reply="Transcript alındı; LLM yanıtı bekleniyor.",
        pending=True,
    )
    return {"ok": True}


def _build_pending_context(pending: dict) -> str:
    title = pending.get("title") or pending["id"]
    preview = (pending.get("body_preview") or "")[:160]
    return f'[SİSTEM: Onay bekleyen görev: "{title}" — {preview}]'


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, authorization: str | None = Header(default=None)) -> ChatOut:
    _auth(authorization)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty text")

    # Admin context: voice "yönetici:" prefix prefix'i her zaman tetikler;
    # panel admin_mode toggle ise yalnız login admin kullanıcıda geçerli.
    text, admin_ctx = auth.admin_context_for_request(text, panel_admin_mode=body.admin_mode)
    if not text:
        raise HTTPException(400, "empty text")

    # Persona seçimi: agent-builder gibi özel trigger'lar korunsun;
    # default match yoksa voice-intake'e düş.
    selected = persona.select_agent(text)
    intake_mode = (selected == config.DEFAULT_AGENT)
    agent_name = "voice-intake" if intake_mode else selected

    pending = _pending_state["draft"]
    prompt = text
    system_notes: list[str] = []
    if intake_mode and pending:
        system_notes.append(_build_pending_context(pending))
    if intake_mode and admin_ctx:
        system_notes.append(
            "[SİSTEM: Admin context aktif. Karmaşık kod değişikliği/refactor/debug"
            " isteklerinde agentic_pi aksiyonu önerebilirsin.]"
        )
    if system_notes:
        prompt = "\n\n".join(system_notes + [text])

    print(
        f"[bridge] → agent={agent_name} session={_state['session_id'] or 'new'} "
        f"pending={bool(pending)} admin={admin_ctx} text={text[:60]!r}",
        flush=True,
    )

    try:
        reply, elapsed = await caller.call_pi(
            prompt,
            agent_name=agent_name,
            session_id=_state["session_id"],
            tools=None,
        )
    except caller.PiTimeout:
        print(f"[bridge] ✗ timeout agent={agent_name}", flush=True)
        events.update_pending_event(text, {
            "status": "error", "agent": agent_name,
            "session": _state["session_id"] or "new",
            "elapsed_ms": 0, "error": "pi timeout", "reply": "",
        }) or events.add_event(
            kind="conversation", status="error", agent=agent_name,
            session=_state["session_id"] or "new", text=text, error="pi timeout",
        )
        raise HTTPException(504, "pi timeout")
    except caller.PiError as exc:
        print(f"[bridge] ✗ exit={exc.returncode} agent={agent_name} err={exc.stderr[:120]!r}", flush=True)
        events.update_pending_event(text, {
            "status": "error", "agent": agent_name,
            "session": _state["session_id"] or "new",
            "elapsed_ms": 0, "error": f"pi exit={exc.returncode}: {exc.stderr[:300]}", "reply": "",
        }) or events.add_event(
            kind="conversation", status="error", agent=agent_name,
            session=_state["session_id"] or "new", text=text,
            error=f"pi exit={exc.returncode}: {exc.stderr[:300]}",
        )
        raise HTTPException(500, f"pi exit={exc.returncode}: {exc.stderr[:300]}")

    # İlk çağrıda --session yoktu; Pi yeni dosya yarattı, en yenisini yakala
    if _state["session_id"] is None:
        latest = caller.latest_session_file()
        if latest:
            _state["session_id"] = latest

    # agent-builder yolu (eski davranış)
    if agent_name == "agent-builder":
        draft = builder.try_parse_builder_draft(reply)
        if draft is not None:
            ok, message = builder.commit_builder_draft(draft)
            print(f"[bridge] builder {'ok' if ok else 'fail'}: {message[:80]}", flush=True)
            reply = message
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000), "reply": reply,
        }) or events.add_event(
            kind="conversation", status="ok", agent=agent_name,
            session=_state["session_id"], text=text, reply=reply,
            elapsed_ms=int(elapsed * 1000),
        )
        return ChatOut(reply=reply, elapsed=elapsed, session_id=_state["session_id"])

    # intake yolu — JSON parse + intent routing
    if not intake_mode:
        # Trigger-match olmuş başka bir persona (recipe, meditation, vb.) — düz reply
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000), "reply": reply,
        }) or events.add_event(
            kind="conversation", status="ok", agent=agent_name,
            session=_state["session_id"], text=text, reply=reply,
            elapsed_ms=int(elapsed * 1000),
        )
        return ChatOut(reply=reply, elapsed=elapsed, session_id=_state["session_id"])

    parsed = intake.parse_intake_json(reply)
    if parsed is None:
        # Pi düzgün JSON dönmedi — fallback olarak ham text'i chat reply sayalım
        print(f"[bridge] ← intake JSON parse fail, fallback ({len(reply)}c)", flush=True)
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000), "reply": reply,
        }) or events.add_event(
            kind="conversation", status="ok", agent=agent_name,
            session=_state["session_id"], text=text, reply=reply,
            elapsed_ms=int(elapsed * 1000),
        )
        return ChatOut(reply=reply, elapsed=elapsed, session_id=_state["session_id"])

    intent = parsed["intent"]
    tts_reply = parsed["tts_reply"]

    if intent == "task":
        # Yeni pending — varsa eskisini sessizce iptal et (Pi yeni intent başlattı)
        if pending:
            intake.delete_pending(pending["id"])
            events.add_event(
                kind="task", status="ok", agent="voice-intake",
                session=_state["session_id"],
                text=f"[önceki pending iptal] {pending.get('title') or pending['id']}",
                reply="yeni görev geldi, eski draft silindi",
            )
        info = intake.write_pending_task(parsed["draft_task"], source="user", admin=admin_ctx)
        _pending_state["draft"] = {
            "id": info["id"],
            "title": info["title"],
            "allowed_actions": info["allowed_actions"],
            "admin": info["admin"],
            "body_preview": info["body_preview"],
            "created_at": info["created"],
        }
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000),
            "reply": f"[pending] {info['title'] or info['id']} — {tts_reply[:80]}",
        }) or events.add_event(
            kind="task", status="ok", agent="voice-intake",
            session=_state["session_id"],
            text=f"[pending] {info['title'] or info['id']}",
            reply=tts_reply, elapsed_ms=int(elapsed * 1000),
        )
        print(f"[bridge] ← intent=task pending={info['id']} elapsed={elapsed:.1f}s", flush=True)

    elif intent == "confirm" and pending:
        intake.move_pending_to_inbox(pending["id"])
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000),
            "reply": f"[onaylandı] {pending.get('title') or pending['id']}",
        }) or events.add_event(
            kind="task", status="ok", agent="voice-intake",
            session=_state["session_id"],
            text=f"[onaylandı] {pending.get('title') or pending['id']}",
            reply=tts_reply, elapsed_ms=int(elapsed * 1000),
        )
        print(f"[bridge] ← intent=confirm moved={pending['id']}", flush=True)
        _pending_state["draft"] = None

    elif intent == "cancel" and pending:
        intake.delete_pending(pending["id"])
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000),
            "reply": f"[iptal] {pending.get('title') or pending['id']}",
        }) or events.add_event(
            kind="task", status="ok", agent="voice-intake",
            session=_state["session_id"],
            text=f"[iptal] {pending.get('title') or pending['id']}",
            reply=tts_reply, elapsed_ms=int(elapsed * 1000),
        )
        print(f"[bridge] ← intent=cancel id={pending['id']}", flush=True)
        _pending_state["draft"] = None

    else:
        # intent=chat veya (confirm/cancel ama pending yok) → düz sohbet
        if intent in ("confirm", "cancel") and not pending:
            print(f"[bridge] ← intent={intent} ama pending yok, chat olarak işle", flush=True)
        events.update_pending_event(text, {
            "status": "ok", "agent": agent_name, "session": _state["session_id"],
            "elapsed_ms": int(elapsed * 1000), "reply": tts_reply,
        }) or events.add_event(
            kind="conversation", status="ok", agent=agent_name,
            session=_state["session_id"], text=text, reply=tts_reply,
            elapsed_ms=int(elapsed * 1000),
        )
        print(f"[bridge] ← intent=chat elapsed={elapsed:.1f}s reply={len(tts_reply)}c", flush=True)

    return ChatOut(
        reply=tts_reply,
        elapsed=elapsed,
        session_id=_state["session_id"],
        intent=intent,
        pending_task=_pending_state["draft"],
    )


@router.post("/chat/reset")
async def reset(authorization: str | None = Header(default=None)) -> dict:
    _auth(authorization)
    _state["session_id"] = None
    events.add_event(
        kind="reset", status="ok", agent=None, session=None,
        text="POST /chat/reset", reply="session reset",
    )
    return {"ok": True}


@router.get("/chat/sessions")
async def chat_sessions() -> dict:
    return {"sessions": caller.list_sessions(), "active": _state["session_id"]}


@router.get("/chat/history")
async def chat_history(session: str | None = None) -> dict:
    sid = session or _state["session_id"]
    msgs = caller.read_session_messages(sid) if sid else []
    return {
        "session": sid,
        "messages": msgs,
        "task_results": intake.enriched_session_tasks(sid) if sid else [],
    }


@router.post("/chat/select")
async def chat_select(body: SelectSessionIn) -> dict:
    if body.session_id is None:
        _state["session_id"] = None
        return {"ok": True, "session_id": None}
    path = config.SESSION_DIR / body.session_id
    if not path.exists():
        raise HTTPException(404, f"session bulunamadı: {body.session_id}")
    _state["session_id"] = body.session_id
    return {"ok": True, "session_id": body.session_id}


@router.get("/chat/pending")
async def get_pending() -> dict:
    return {"pending": _pending_state["draft"]}


@router.post("/chat/confirm-pending")
async def confirm_pending() -> dict:
    pending = _pending_state["draft"]
    if not pending:
        raise HTTPException(404, "onay bekleyen görev yok")
    intake.move_pending_to_inbox(pending["id"])
    title = pending.get("title") or pending["id"]
    # Sidecar'a kaydet: sayfa yenilenince chat'te sonuç kartı doğru
    # pozisyonda (kullanıcının onayladığı turn'ün altında) yeniden basılsın.
    if _state["session_id"]:
        msg_count = len(caller.read_session_messages(_state["session_id"]))
        intake.record_session_task(_state["session_id"], pending["id"], msg_count)
    events.add_event(
        kind="task", status="ok", agent="panel-button",
        session=_state["session_id"],
        text=f"[onaylandı] {title}", reply=f"{title} kuyruğa alındı",
    )
    print(f"[bridge] panel confirm: {pending['id']}", flush=True)
    _pending_state["draft"] = None
    return {"ok": True, "task_id": pending["id"]}


@router.post("/chat/cancel-pending")
async def cancel_pending() -> dict:
    pending = _pending_state["draft"]
    if not pending:
        raise HTTPException(404, "onay bekleyen görev yok")
    intake.delete_pending(pending["id"])
    title = pending.get("title") or pending["id"]
    events.add_event(
        kind="task", status="ok", agent="panel-button",
        session=_state["session_id"],
        text=f"[iptal] {title}", reply=f"{title} silindi",
    )
    print(f"[bridge] panel cancel: {pending['id']}", flush=True)
    _pending_state["draft"] = None
    return {"ok": True, "task_id": pending["id"]}


@router.get("/chat/task-status/{task_id}")
async def chat_task_status(task_id: str) -> dict:
    """Onaylanmış task'ın güncel durumu — chat UI confirm sonrası buradan
    polling yapar; processing→done/failed olduğunda sonuç bubble basar."""
    info = intake.task_status(task_id)
    if not info:
        raise HTTPException(404, f"task bulunamadı: {task_id}")
    return info
