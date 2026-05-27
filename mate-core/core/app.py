"""Mate Core — FastAPI app assembly.

Tüm router'ları monte eder, request_monitor middleware'i ekler, dashboard
HTML'ini geriye uyum için `/dashboard`'da bırakır (Faz 5'te `/panel/events`'e
taşınacak), service-health ve events SSE endpoint'lerini içerir.
"""
from __future__ import annotations

import asyncio
import html
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from autonomous import watcher
from core import config, events
from core.agent_endpoints import router as agent_router
from core.auth_routes import router as auth_router
from panel.routes import router as panel_router
from voice_bridge.routes import router as voice_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: otonom watcher'ı arka planda başlat. Shutdown: cancel et."""
    watcher_task = asyncio.create_task(watcher.run())
    print("[core] lifespan: autonomous watcher started", flush=True)
    try:
        yield
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except (asyncio.CancelledError, Exception):
            pass
        print("[core] lifespan: autonomous watcher stopped", flush=True)


app = FastAPI(title="mate-core", lifespan=lifespan)
app.include_router(voice_router)
app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(panel_router)


_NOISY_PATHS = {"/dashboard", "/events", "/events/stream", "/health", "/service-health"}
_NOISY_PREFIXES = ("/panel/", "/panel", "/agent/jobs")  # HEAD veya method-mismatch 405'leri sessiz


@app.middleware("http")
async def request_monitor(request: Request, call_next):
    started = time.monotonic()
    response = await call_next(request)
    path = request.url.path
    if response.status_code >= 400 and path not in _NOISY_PATHS and not any(
        path.startswith(p) for p in _NOISY_PREFIXES
    ):
        events.add_event(
            kind="http", status="error", agent=None, session=None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            text=f"{request.method} {path} from {request.client.host if request.client else '-'}",
            reply=f"HTTP {response.status_code}",
        )
    return response


def _check_url(name: str, url: str, accepted_statuses: set[int] | None = None) -> dict:
    accepted_statuses = accepted_statuses or set()
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "mate-core-health/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=config.SERVICE_CHECK_TIMEOUT_SEC) as resp:
            ok = 200 <= resp.status < 300 or resp.status in accepted_statuses
            return {
                "name": name, "ok": ok, "status": resp.status, "url": url,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "error": None if ok else f"HTTP {resp.status}",
            }
    except urllib.error.HTTPError as exc:
        ok = exc.code in accepted_statuses
        return {
            "name": name, "ok": ok, "status": exc.code, "url": url,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": None if ok else f"HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "name": name, "ok": False, "status": None, "url": url,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": str(exc)[:160],
        }


async def _collect_service_health() -> dict:
    stt_task = asyncio.to_thread(_check_url, "STT", f"{config.STT_BASE_URL}/v1/audio/transcriptions", {404, 405})
    tts_task = asyncio.to_thread(_check_url, "TTS", f"{config.TTS_BASE_URL}/v1/voices")
    stt, tts = await asyncio.gather(stt_task, tts_task)
    return {
        "services": [
            {"name": "Bridge", "ok": True, "status": 200, "url": "local", "elapsed_ms": 0, "error": None},
            stt, tts,
        ]
    }


@app.get("/service-health")
async def service_health(request: Request, token: str | None = Query(default=None)) -> dict:
    return await _collect_service_health()


@app.get("/events/stream")
async def events_stream(request: Request, token: str | None = Query(default=None)) -> StreamingResponse:
    async def generate():
        queue = events.subscribe()
        try:
            yield events.sse({"type": "events", "events": events.all_events()})
            yield events.sse({"type": "services", **await _collect_service_health()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    await asyncio.wait_for(queue.get(), timeout=5)
                    yield events.sse({"type": "events", "events": events.all_events()})
                except asyncio.TimeoutError:
                    yield events.sse({"type": "services", **await _collect_service_health()})
        finally:
            events.unsubscribe(queue)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/events")
async def events_endpoint(request: Request, token: str | None = Query(default=None)) -> dict:
    return {"events": events.all_events()}


@app.get("/dashboard", include_in_schema=False)
async def dashboard_redirect():
    return RedirectResponse("/panel/events", status_code=301)


@app.get("/_dashboard_legacy", response_class=HTMLResponse, include_in_schema=False)
async def _dashboard_legacy(request: Request, token: str | None = Query(default=None)) -> HTMLResponse:
    safe_token = html.escape(token or "")
    return HTMLResponse(f"""
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mate Core Dashboard</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;margin:0;background:#0f1117;color:#e8e8e8}}
header{{position:sticky;top:0;background:#171a23;padding:14px 18px;border-bottom:1px solid #2b3040;z-index:2}}
h1{{font-size:18px;margin:0}} .meta{{color:#9aa4b2;font-size:13px;margin-top:4px}}
.top{{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}}
.services{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.service{{display:flex;gap:6px;align-items:center;font-size:12px;padding:5px 8px;border-radius:999px;background:#2b3040;color:#cdd6e3}}
.dot{{width:9px;height:9px;border-radius:50%;background:#77808f;box-shadow:0 0 0 rgba(119,128,143,.0)}}
.dot.ok{{background:#29d17d;animation:pulse-ok 1.4s infinite}}
.dot.err{{background:#ff4d6d;animation:pulse-err 1.0s infinite}}
@keyframes pulse-ok{{0%{{box-shadow:0 0 0 0 rgba(41,209,125,.55)}}70%{{box-shadow:0 0 0 7px rgba(41,209,125,0)}}100%{{box-shadow:0 0 0 0 rgba(41,209,125,0)}}}}
@keyframes pulse-err{{0%{{box-shadow:0 0 0 0 rgba(255,77,109,.65)}}70%{{box-shadow:0 0 0 8px rgba(255,77,109,0)}}100%{{box-shadow:0 0 0 0 rgba(255,77,109,0)}}}}
main{{padding:14px}} .card{{background:#171a23;border:1px solid #2b3040;border-radius:12px;padding:12px;margin-bottom:12px}}
.row{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}}
.badge{{font-size:12px;padding:3px 7px;border-radius:999px;background:#2b3040;color:#cdd6e3}}
.ok{{background:#163d2b;color:#b7f7d1}} .err{{background:#4a1d24;color:#ffb6c1}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0f1117;border-radius:8px;padding:10px;margin:8px 0 0}}
small{{color:#9aa4b2}} button{{font-size:14px;padding:7px 10px;border-radius:8px;border:0}}
</style>
<header><div class="top"><div><h1>Mate Core Dashboard</h1><div class="meta">SSE ile canlı güncellenir; sayfa refresh yapmaz.</div></div><div id="services" class="services"></div></div></header>
<main><div class="row"><button onclick="reconnect()">Yeniden bağlan</button><span id="status" class="badge">bağlanıyor</span></div><div id="events"></div></main>
<script>
const token = "{safe_token}";
let source = null;
function esc(s) {{ return String(s ?? "").replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c])); }}
function serviceHtml(s) {{
  const cls = s.ok ? 'ok' : 'err';
  const title = `${{s.url}} ${{s.status ? 'HTTP ' + s.status : ''}} ${{s.error || ''}} ${{s.elapsed_ms ?? 0}}ms`;
  return `<span class="service" title="${{esc(title)}}"><span class="dot ${{cls}}"></span>${{esc(s.name)}}</span>`;
}}
function renderEvents(events) {{
  document.getElementById('events').innerHTML = events.map(e => `
    <div class="card">
      <div class="row">
        <span class="badge">${{esc(e.ts)}}</span>
        <span class="badge ${{e.status === 'error' ? 'err' : 'ok'}}">${{esc(e.status)}}</span>
        <span class="badge">${{esc(e.kind)}}</span>
        <span class="badge">agent: ${{esc(e.agent || '-')}}</span>
        <span class="badge">${{esc(e.elapsed_ms || 0)}} ms</span>
        <span class="badge">session: ${{esc(e.session || '-')}}</span>
      </div>
      <small>İstek</small><pre>${{esc(e.text)}}</pre>
      <small>Yanıt / hata</small><pre>${{esc(e.reply || e.error || '')}}</pre>
    </div>`).join('');
}}
function renderServices(services) {{
  document.getElementById('services').innerHTML = services.map(serviceHtml).join('');
}}
function connect() {{
  const status = document.getElementById('status');
  source = new EventSource('/events/stream?token=' + encodeURIComponent(token));
  source.onopen = () => {{
    status.textContent = 'canlı bağlı';
    status.className = 'badge ok';
  }};
  source.onmessage = (ev) => {{
    const data = JSON.parse(ev.data);
    if (data.type === 'events') renderEvents(data.events || []);
    if (data.type === 'services') renderServices(data.services || []);
    status.textContent = 'canlı ' + new Date().toLocaleTimeString();
    status.className = 'badge ok';
  }};
  source.onerror = () => {{
    status.textContent = 'SSE yeniden bağlanıyor…';
    status.className = 'badge err';
  }};
}}
function reconnect() {{
  if (source) source.close();
  connect();
}}
connect();
</script>
""")
