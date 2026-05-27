"""Mate Core — yönetim paneli (4 sayfa).

GET /panel              → /panel/events redirect
GET /panel/events       → Olaylar + STT/TTS/Bridge health pulse (SSE canlı)
GET /panel/tasks        → inbox/processing/done/failed listesi, butonlar
GET /panel/jobs         → scheduler job listesi, run now / remove
GET /panel/sessions     → Pi session jsonl listesi + persona dosyaları
GET /dashboard          → 301 redirect (geriye uyum)

Task/job butonları için POST/DELETE endpoint'leri panel/routes.py içinde
(/agent/jobs/{id} ile uyumlu, /panel/tasks/{name}/rerun yeni).
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from autonomous import frontmatter
from core import auth, config

router = APIRouter()


_CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;margin:0;background:#0f1117;color:#e8e8e8}
header{position:sticky;top:0;background:#171a23;padding:14px 18px;border-bottom:1px solid #2b3040;z-index:2}
h1{font-size:18px;margin:0 0 8px}
.title{display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap}
nav{display:flex;gap:6px;flex-wrap:wrap}
nav a{text-decoration:none;color:#cdd6e3;font-size:13px;padding:5px 11px;border-radius:999px;background:#2b3040}
nav a.active{background:#3d4761;color:#fff}
.services{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:4px}
.service{display:flex;gap:6px;align-items:center;font-size:12px;padding:5px 8px;border-radius:999px;background:#2b3040;color:#cdd6e3}
.dot{width:9px;height:9px;border-radius:50%;background:#77808f}
.dot.ok{background:#29d17d;animation:pulse-ok 1.4s infinite}
.dot.err{background:#ff4d6d;animation:pulse-err 1.0s infinite}
@keyframes pulse-ok{0%{box-shadow:0 0 0 0 rgba(41,209,125,.55)}70%{box-shadow:0 0 0 7px rgba(41,209,125,0)}100%{box-shadow:0 0 0 0 rgba(41,209,125,0)}}
@keyframes pulse-err{0%{box-shadow:0 0 0 0 rgba(255,77,109,.65)}70%{box-shadow:0 0 0 8px rgba(255,77,109,0)}100%{box-shadow:0 0 0 0 rgba(255,77,109,0)}}
main{padding:14px}
.card{background:#171a23;border:1px solid #2b3040;border-radius:12px;padding:12px;margin-bottom:12px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.badge{font-size:12px;padding:3px 7px;border-radius:999px;background:#2b3040;color:#cdd6e3}
.ok{background:#163d2b;color:#b7f7d1}
.err{background:#4a1d24;color:#ffb6c1}
.warn{background:#3d3517;color:#ffe7a8}
pre{white-space:pre-wrap;word-break:break-word;background:#0f1117;border-radius:8px;padding:10px;margin:8px 0 0;font-size:12px}
small{color:#9aa4b2}
button{font-size:13px;padding:6px 10px;border-radius:8px;border:0;background:#3d4761;color:#fff;cursor:pointer}
button.danger{background:#5a1d24}
button:hover{filter:brightness(1.15)}
.empty{color:#9aa4b2;padding:24px;text-align:center;background:#171a23;border-radius:12px;border:1px dashed #2b3040}
.board{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:start}
.board.two{grid-template-columns:repeat(2,minmax(0,1fr))}
.col{background:#131620;border:1px solid #2b3040;border-radius:12px;padding:10px;min-height:140px}
.col-head{font-size:14px;color:#cdd6e3;padding:6px 4px 10px;border-bottom:1px solid #2b3040;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center}
.col-body{display:flex;flex-direction:column;gap:10px;max-height:75vh;overflow-y:auto}
.col-body .card{margin-bottom:0}
.col[data-status=inbox] .col-head{color:#ffe7a8}
.col[data-status=processing] .col-head{color:#9ec1ff}
.col[data-status=done] .col-head{color:#b7f7d1}
.col[data-status=failed] .col-head{color:#ffb6c1}
.col[data-status=processing] .card{border-color:#3a4a6d;box-shadow:0 0 0 1px rgba(60,120,255,.25)}
.col[data-status=active] .col-head{color:#b7f7d1}
.col[data-status=paused] .col-head{color:#ffe7a8}
.col[data-status=paused] .card{opacity:.78}
.ios-card{padding:14px 16px;border-radius:14px}
.ios-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:8px}
.ios-title{font-size:16px;font-weight:600;color:#fff;letter-spacing:.01em;word-break:break-word;line-height:1.25;flex:1;min-width:0}
.ios-subtitle{font-size:11.5px;color:#8a92a3;margin-top:2px;font-weight:400}
.ios-actions{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end;flex-shrink:0}
.ios-actions button{font-size:11px;padding:4px 8px;border-radius:7px;background:#2b3040;color:#e8e8e8}
.ios-actions button:not(.danger):not(:disabled):hover{background:#3d4761}
.ios-actions button.danger{background:transparent;color:#ff8090;border:1px solid #4a1d24;padding:3px 7px}
.ios-actions button.danger:hover{background:#5a1d24;color:#fff}
.ios-actions button:disabled{opacity:.35;cursor:not-allowed}
.ios-section{margin:10px 0 8px}
.ios-label{font-size:10px;color:#8a92a3;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;font-weight:500}
.ios-value{font-size:13px;color:#cdd6e3;font-family:ui-monospace,Menlo,Consolas,monospace;word-break:break-word}
.ios-body-text{font-size:13.5px;color:#e8e8e8;line-height:1.45;white-space:pre-wrap;word-break:break-word}
.ios-terminal{background:#0a0d14;border:1px solid #1d2230;border-radius:8px;padding:7px 10px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#b7f7d1;white-space:pre-wrap;word-break:break-word;min-height:18px}
.ios-terminal.empty{color:#5a6172}
.ios-terminal.err{color:#ff8090}
.ios-chips{display:flex;gap:5px;flex-wrap:wrap;margin-top:12px;padding-top:10px;border-top:1px solid #2b3040}
.ios-chips .badge{font-size:10.5px;padding:2px 6px}
.metrics-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:14px}
.metric-card{background:#171a23;border:1px solid #2b3040;border-radius:12px;padding:12px 14px}
.metric-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}
.metric-title{font-size:11px;color:#8a92a3;text-transform:uppercase;letter-spacing:.06em;font-weight:500}
.metric-count{font-size:11px;color:#cdd6e3}
.metric-big{font-size:22px;font-weight:600;color:#fff;letter-spacing:.01em;line-height:1}
.metric-unit{font-size:13px;color:#9aa4b2;font-weight:400;margin-left:2px}
.metric-sub{font-size:11px;color:#8a92a3;margin-top:6px}
.metric-card[data-kind=conversation] .metric-big{color:#b7f7d1}
.metric-card[data-kind=task] .metric-big{color:#9ec1ff}
.metric-card[data-kind=job] .metric-big{color:#ffe7a8}
@media (max-width:700px){.metrics-strip{grid-template-columns:1fr}}
.chat-shell{display:flex;flex-direction:column;gap:10px;height:calc(100vh - 130px);max-width:780px;margin:0 auto}
.chat-toolbar{display:flex;justify-content:space-between;align-items:center;gap:8px}
.chat-toolbar small{color:#8a92a3;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px}
.chat-toolbar select{background:#171a23;color:#e8e8e8;border:1px solid #2b3040;border-radius:8px;padding:6px 10px;font-size:12px;max-width:560px;flex:1}
.chat-toolbar select:focus{outline:none;border-color:#3d6dff}
.chat-messages{flex:1;overflow-y:auto;background:#0f1117;border:1px solid #2b3040;border-radius:14px;padding:14px;display:flex;flex-direction:column;gap:10px}
.bubble{max-width:78%;padding:9px 13px;border-radius:16px;font-size:14px;line-height:1.4;word-break:break-word;white-space:pre-wrap}
.bubble.user{align-self:flex-end;background:#2c3a5a;color:#fff;border-bottom-right-radius:6px}
.bubble.agent{align-self:flex-start;background:#1f2330;color:#e8e8e8;border:1px solid #2b3040;border-bottom-left-radius:6px}
.bubble.err{background:#3d1d24;color:#ffb6c1;border-color:#5a1d24}
.bubble.thinking{align-self:flex-start;background:#1f2330;color:#8a92a3;font-style:italic;border:1px dashed #2b3040;border-bottom-left-radius:6px}
.bubble-meta{font-size:10px;color:#8a92a3;margin-top:4px;text-align:right;font-family:ui-monospace,Menlo,Consolas,monospace}
.bubble.user .bubble-meta{color:#a8b4d0}
.chat-input{display:flex;gap:8px;align-items:flex-end;background:#171a23;border:1px solid #2b3040;border-radius:14px;padding:10px}
.chat-input textarea{flex:1;background:transparent;color:#e8e8e8;border:0;outline:none;font:14px/1.4 -apple-system,BlinkMacSystemFont,system-ui,sans-serif;resize:none;min-height:40px;max-height:160px}
.chat-input button{padding:8px 14px;background:#3d6dff;color:#fff;border-radius:10px;font-size:14px;font-weight:500}
.chat-input button:disabled{opacity:.35;cursor:wait}
.chat-empty{color:#5a6172;text-align:center;padding:40px 20px;font-style:italic}
.pending-card{align-self:flex-start;max-width:78%;background:linear-gradient(180deg,#2a2510,#1f1d10);border:1px solid #4a3d17;border-radius:14px;padding:12px 14px;color:#e8e8e8}
.pending-head{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.pending-head .badge.warn{background:#3d3517;color:#ffe7a8;font-weight:500}
.pending-title{font-weight:600;color:#ffe7a8;font-size:14px}
.pending-body{color:#cdd6e3;font-size:13px;line-height:1.4;margin-bottom:10px;white-space:pre-wrap;word-break:break-word;max-height:120px;overflow-y:auto}
.pending-chips{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}
.pending-chips .badge{font-size:10.5px;padding:2px 6px;background:#2b3040}
.pending-actions{display:flex;gap:8px;justify-content:flex-end}
.pending-actions button{font-size:13px;padding:6px 12px;border-radius:8px;border:0;cursor:pointer;font-weight:500}
.pending-actions .confirm-btn{background:#1d4b2c;color:#b7f7d1}
.pending-actions .confirm-btn:hover{background:#2c6a3d}
.pending-actions .cancel-btn{background:transparent;color:#ff8090;border:1px solid #4a1d24}
.pending-actions .cancel-btn:hover{background:#5a1d24;color:#fff}
.pending-actions button:disabled{opacity:.4;cursor:wait}
@media (max-width:1000px){.board:not(.two){grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.board,.board.two{grid-template-columns:1fr}}
.user-host{position:relative}
.user-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;background:#2b3040;color:#cdd6e3;font-size:12px;cursor:pointer;border:0;font-family:inherit;line-height:1.2}
.user-chip:hover{background:#3d4761;color:#fff}
.user-chip.logged-out{background:#3d2b1a;color:#ffd9a8}
.user-chip.setup{background:#5a1d24;color:#ffb6c1;animation:pulse-err 1.4s infinite}
.user-chip .shield{color:#ffd485;font-size:11px}
.user-menu{position:absolute;top:calc(100% + 6px);right:0;background:#171a23;border:1px solid #2b3040;border-radius:10px;padding:6px;min-width:200px;display:none;z-index:50;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.user-menu.open{display:block}
.user-menu .item{padding:7px 10px;border-radius:6px;color:#cdd6e3;font-size:13px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:8px}
.user-menu .item:hover{background:#2b3040;color:#fff}
.user-menu .item.active{color:#b7f7d1;background:#163d2b}
.user-menu .divider{height:1px;background:#2b3040;margin:5px 0}
.user-menu .label{font-size:10px;color:#5a6172;text-transform:uppercase;letter-spacing:.06em;padding:6px 10px 2px;font-weight:500}
.admin-toggle{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;background:#2b3040;color:#cdd6e3;font-size:12px;cursor:pointer;border:0;font-family:inherit;line-height:1.2}
.admin-toggle.on{background:#3a2c1a;color:#ffd485;box-shadow:0 0 0 1px #5a4017 inset}
.admin-toggle .dot{width:8px;height:8px;border-radius:50%;background:#5a6172;transition:all .15s}
.admin-toggle.on .dot{background:#ffd485;box-shadow:0 0 6px rgba(255,212,133,.5)}
.admin-toggle:disabled{opacity:.4;cursor:not-allowed}
.user-card-row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px}
.user-card-form{background:#171a23;border:1px dashed #2b3040;border-radius:12px;padding:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.user-card-form input{background:#0f1117;border:1px solid #2b3040;border-radius:8px;color:#e8e8e8;padding:7px 10px;font-size:13px;flex:1;min-width:160px;font-family:inherit}
.user-card-form input:focus{outline:none;border-color:#3d6dff}
.setup-banner{background:linear-gradient(180deg,#3d2b1a,#2a1d10);border:1px solid #5a4017;border-radius:12px;padding:14px 16px;margin-bottom:14px;color:#ffd9a8}
.setup-banner h3{margin:0 0 6px;color:#ffe7a8;font-size:15px}
.setup-banner p{margin:0;font-size:13px;line-height:1.4;color:#cdd6e3}
.task-result-card{align-self:flex-start;max-width:82%;background:linear-gradient(180deg,#152318,#0e1813);border:1px solid #2a4a32;border-radius:14px;padding:12px 14px}
.task-result-card.failed{background:linear-gradient(180deg,#2a1518,#1a0d10);border-color:#5a1d24}
.task-result-card.running{background:linear-gradient(180deg,#15192a,#0d101a);border-color:#2a3a5a}
.task-result-card.running .task-result-title{color:#9ec1ff}
.task-result-card.running .badge.ok,.task-result-card.running .badge.err{background:#1f2942;color:#9ec1ff;animation:pulse-run 1.6s infinite}
@keyframes pulse-run{0%{opacity:.55}50%{opacity:1}100%{opacity:.55}}
.task-modal-backdrop{position:fixed;inset:0;background:rgba(8,10,16,.78);backdrop-filter:blur(6px);display:none;align-items:flex-start;justify-content:center;padding:5vh 4vw;z-index:100;overflow-y:auto}
.task-modal-backdrop.open{display:flex}
.task-modal{background:#171a23;border:1px solid #2b3040;border-radius:14px;width:min(900px,100%);max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.task-modal-head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid #2b3040;gap:10px}
.task-modal-title{font-size:15px;font-weight:600;color:#fff;flex:1;min-width:0;word-break:break-word}
.task-modal-meta{font-size:11px;color:#8a92a3;font-family:ui-monospace,Menlo,Consolas,monospace}
.task-modal-close{background:transparent;border:1px solid #3d4761;color:#cdd6e3;padding:5px 10px;border-radius:8px;font-size:13px;cursor:pointer}
.task-modal-close:hover{background:#3d4761;color:#fff}
.task-modal-body{padding:14px 18px;overflow-y:auto;flex:1}
.task-modal-body pre{white-space:pre-wrap;word-break:break-word;background:#0a0d14;border:1px solid #1d2230;border-radius:8px;padding:12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;color:#cdd6e3;line-height:1.55;margin:0}
.ios-card.clickable{cursor:pointer}
.ios-card.clickable:hover{border-color:#3d4761}
.task-result-head{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
.task-result-title{font-weight:600;color:#b7f7d1;font-size:14px;line-height:1.25}
.task-result-card.failed .task-result-title{color:#ffb6c1}
.task-result-meta{margin-left:auto;font-size:11px;color:#8a92a3;font-family:ui-monospace,Menlo,Consolas,monospace}
.task-result-summary{color:#cdd6e3;font-size:13px;line-height:1.45;margin:6px 0 8px;white-space:pre-wrap;word-break:break-word}
.task-result-action{background:#0a0d14;border:1px solid #1d2230;border-radius:8px;padding:8px 10px;margin-top:6px}
.task-result-action-head{display:flex;gap:5px;align-items:center;margin-bottom:5px;font-size:11px;flex-wrap:wrap}
.task-result-action-preview{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;color:#b7f7d1;white-space:pre-wrap;word-break:break-word;max-height:240px;overflow-y:auto;margin:0}
.task-result-card.failed .task-result-action-preview{color:#ffb6c1}
.task-result-card .badge.ok{background:#163d2b;color:#b7f7d1}
.task-result-card .badge.err{background:#4a1d24;color:#ffb6c1}
"""


_NAV_TABS = [
    ("chat", "Sohbet"),
    ("events", "Olaylar"),
    ("tasks", "Görevler"),
    ("jobs", "Job'lar"),
    ("sessions", "Oturumlar"),
    ("users", "Kullanıcılar"),
]


# User-chip her sayfada üst-sağda görünür; JS /auth/me'yi çağırır, kullanıcılar
# arası geçiş + çıkış burada. setup_required ise kırmızı uyarı modunda.
_USER_CHIP_SCRIPT = """
<script>
(async function(){
  function $(s){return document.querySelector(s)}
  function esc(s){return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  const chip = $('#user-chip'), menu = $('#user-menu');
  if (!chip || !menu) return;
  let me = null;
  async function loadMe(){
    try {
      const r = await fetch('/auth/me', {cache:'no-store'});
      me = await r.json();
      window.__authMe = me;
      render();
      document.dispatchEvent(new CustomEvent('auth:loaded', {detail: me}));
    } catch(e){ chip.textContent = '⚠ auth?'; }
  }
  function render(){
    chip.classList.remove('logged-out','setup');
    if (me.setup_required){
      chip.classList.add('setup');
      chip.innerHTML = '⚠ Setup gerek';
      return;
    }
    const u = me.user;
    if (!u){
      chip.classList.add('logged-out');
      chip.innerHTML = '👤 Giriş yap';
      return;
    }
    chip.innerHTML = '👤 ' + esc(u.username) + (u.admin ? ' <span class="shield">🛡</span>' : '');
  }
  chip.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (me && me.setup_required){ location.href = '/panel/users'; return; }
    if (menu.classList.contains('open')){ menu.classList.remove('open'); return; }
    const r = await fetch('/auth/users', {cache:'no-store'});
    const d = await r.json();
    const cur = (me && me.user && me.user.username) || null;
    const items = [];
    items.push('<div class="label">Geçiş</div>');
    for (const u of (d.users || [])){
      const isMe = u.username === cur;
      items.push(`<div class="item ${isMe?'active':''}" data-login="${esc(u.username)}">${esc(u.username)}${u.admin?' 🛡':''}${isMe?' <span>✓</span>':''}</div>`);
    }
    items.push('<div class="divider"></div>');
    if (cur) items.push('<div class="item" data-action="logout">Çıkış</div>');
    items.push('<div class="item" data-action="manage">Kullanıcıları Yönet…</div>');
    menu.innerHTML = items.join('');
    menu.classList.add('open');
  });
  document.addEventListener('click', async (e) => {
    const item = e.target.closest('.user-menu .item');
    if (!item){
      if (!e.target.closest('.user-host')) menu.classList.remove('open');
      return;
    }
    e.stopPropagation();
    if (item.dataset.action === 'logout'){
      await fetch('/auth/logout', {method:'POST'});
      location.reload();
    } else if (item.dataset.action === 'manage'){
      location.href = '/panel/users';
    } else if (item.dataset.login){
      const username = item.dataset.login;
      await fetch('/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username})});
      location.reload();
    }
  });
  loadMe();
})();
</script>
"""


def _nav(active: str) -> str:
    return "".join(
        f'<a href="/panel/{slug}" class="{"active" if slug == active else ""}">{label}</a>'
        for slug, label in _NAV_TABS
    )


def _layout(title: str, active: str, body: str, *, with_services: bool = False) -> str:
    services_html = '<div id="services" class="services"></div>' if with_services else ""
    return f"""<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — Mate Core</title>
<style>{_CSS}</style>
<header>
  <div class="title">
    <h1>Mate Core — {html.escape(title)}</h1>
    <nav>{_nav(active)}</nav>
    <div class="user-host">
      <button class="user-chip" id="user-chip" type="button">yükleniyor…</button>
      <div class="user-menu" id="user-menu"></div>
    </div>
  </div>
  {services_html}
</header>
<main>{body}</main>
{_USER_CHIP_SCRIPT}
"""


# ---------- /panel root → chat ----------

@router.get("/panel")
async def panel_root():
    return RedirectResponse("/panel/chat", status_code=302)


# ---------- /panel/chat ----------

_CHAT_BODY = """
<div class="chat-shell">
  <div class="chat-toolbar">
    <select id="session-picker" title="Aktif oturum">
      <option value="">⏳ yükleniyor…</option>
    </select>
    <button class="admin-toggle" id="admin-toggle" type="button" disabled title="Yönetici modu — bu sohbette agentic_pi aksiyonu izinli olur. Sadece admin kullanıcılarda aktif.">
      <span class="dot"></span><span>Yönetici</span>
    </button>
    <button class="danger" id="reset-btn" title="Bridge'in aktif session'ını sıfırla">Sıfırla</button>
  </div>
  <div class="chat-messages" id="messages">
    <div class="chat-empty" id="empty">Mate ile yazışmaya başla. ⌘/Ctrl+Enter ile gönder.</div>
  </div>
  <form class="chat-input" id="chat-form">
    <textarea id="input" rows="1" placeholder="Mesaj yaz…" autofocus></textarea>
    <button type="submit" id="send-btn">Gönder</button>
  </form>
</div>
<script>
const messagesEl = document.getElementById('messages');
const emptyEl = document.getElementById('empty');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const picker = document.getElementById('session-picker');
const resetBtn = document.getElementById('reset-btn');
const adminToggle = document.getElementById('admin-toggle');

// Yönetici toggle: localStorage'da saklanır, sadece admin kullanıcılarda aktif.
// /auth/me yüklendiğinde enable/disable + persisted state restore edilir.
let adminMode = localStorage.getItem('mate.adminMode') === '1';
function renderAdminToggle(){
  if (adminMode) adminToggle.classList.add('on'); else adminToggle.classList.remove('on');
}
document.addEventListener('auth:loaded', (e) => {
  const me = e.detail;
  const canAdmin = !!(me && me.user && me.user.admin);
  adminToggle.disabled = !canAdmin;
  if (!canAdmin && adminMode){
    adminMode = false;
    localStorage.setItem('mate.adminMode', '0');
  }
  renderAdminToggle();
});
adminToggle.addEventListener('click', () => {
  if (adminToggle.disabled) return;
  adminMode = !adminMode;
  localStorage.setItem('mate.adminMode', adminMode ? '1' : '0');
  renderAdminToggle();
});
renderAdminToggle();

function esc(s){return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtMtime(epoch){
  if (!epoch) return '';
  const d = new Date(epoch * 1000);
  const pad = n => String(n).padStart(2,'0');
  return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// taskResults: tamamlanmış görev sonuçları, her biri {afterMessageCount, data}.
// afterMessageCount = task tamamlandığı an history mesaj sayısı; render
// kart'ı o mesajın hemen altına yerleştirir.
let state = {messages: [], session_id: null, pending: [], pendingTask: null, taskResults: []};

async function loadPendingTask(){
  try {
    const r = await fetch('/chat/pending', {cache:'no-store'});
    const d = await r.json();
    state.pendingTask = d.pending || null;
  } catch (e) { console.error('pending load', e); }
}

async function loadSessions(){
  try {
    const r = await fetch('/chat/sessions', {cache:'no-store'});
    const d = await r.json();
    state.session_id = d.active || null;
    const opts = [`<option value="">✨ Yeni sohbet</option>`];
    for (const s of (d.sessions || [])) {
      const label = `${fmtMtime(s.mtime)} · ${s.messages} msg — ${(s.first_user || '(boş)').slice(0,40)}`;
      const selected = s.name === d.active ? ' selected' : '';
      opts.push(`<option value="${esc(s.name)}"${selected}>${esc(label)}</option>`);
    }
    picker.innerHTML = opts.join('');
    if (d.active && !state.session_id) state.session_id = d.active;
  } catch (e) { console.error('sessions load', e); }
}

async function loadHistory(){
  try {
    const r = await fetch('/chat/history', {cache:'no-store'});
    const d = await r.json();
    state.messages = (d.messages || []).map(m => ({role: m.role === 'assistant' ? 'agent' : m.role, text: m.text}));
    state.session_id = d.session;
    // Sidecar'dan onaylanmış görev kartlarını yeniden yükle. In-flight
    // (poll devam eden) lokal entry'leri bozmamak için sadece henüz state'te
    // olmayan task_id'leri ekle.
    const existingIds = new Set(state.taskResults.map(t => (t.data && t.data.id) || ''));
    for (const t of (d.task_results || [])){
      const id = (t.data && t.data.id) || '';
      if (id && !existingIds.has(id)){
        const entry = {afterMessageCount: t.after_message_count, data: t.data};
        state.taskResults.push(entry);
        // Hâlâ koşuyorsa polling başlat — kart canlı güncellensin
        if (t.data.status !== 'done' && t.data.status !== 'failed'){
          pollResultUpdate(id, entry);
        }
      }
    }
    render();
  } catch (e) { console.error('history load', e); }
}

function createBubbleRow(m){
  const row = document.createElement('div');
  row.className = 'bubble-row';
  row.style.display = 'flex';
  row.style.flexDirection = 'column';
  row.style.alignSelf = m.role === 'user' ? 'flex-end' : 'flex-start';
  row.style.maxWidth = '78%';
  const cls = m.role === 'user' ? 'bubble user'
            : m.error ? 'bubble err'
            : m.thinking ? 'bubble thinking'
            : 'bubble agent';
  const meta = [];
  if (m.ts) meta.push(m.ts);
  if (m.elapsed_s) meta.push(m.elapsed_s.toFixed(1) + 's');
  row.innerHTML = `<div class="${cls}">${esc(m.text)}</div>` +
                  (meta.length ? `<div class="bubble-meta">${esc(meta.join(' · '))}</div>` : '');
  return row;
}

function createTaskResultCard(d){
  const failed = d.status === 'failed';
  const inProgress = d.status !== 'done' && d.status !== 'failed';
  const card = document.createElement('div');
  let cls = 'task-result-card';
  if (failed) cls += ' failed';
  else if (inProgress) cls += ' running';
  card.className = cls;
  const statusBadge = failed ? '✗ Başarısız' : inProgress ? '⏳ Çalışıyor' : '✓ Tamamlandı';
  const elapsed = d.elapsed_s ? (Number(d.elapsed_s).toFixed(1) + 's') : '';
  const actionsHtml = (d.actions || []).map(a => {
    const cls = a.status === 'ok' ? 'ok' : 'err';
    const elapsedAct = a.elapsed_s ? ` <small>${Number(a.elapsed_s).toFixed(1)}s</small>` : '';
    const head = `<span class="badge">${esc(a.type || '?')}</span><span class="badge ${cls}">${esc(a.status || '?')}</span>${elapsedAct}`;
    const preview = (a.preview || '').trim();
    return `<div class="task-result-action"><div class="task-result-action-head">${head}</div>${preview ? `<pre class="task-result-action-preview">${esc(preview)}</pre>` : ''}</div>`;
  }).join('');
  const errBlock = d.error
    ? `<div class="task-result-summary" style="color:#ffb6c1">${esc(d.error)}</div>` : '';
  const summaryBlock = d.summary
    ? `<div class="task-result-summary">${esc(d.summary)}</div>` : '';
  card.innerHTML = `
    <div class="task-result-head">
      <span class="badge ${failed?'err':'ok'}">${statusBadge}</span>
      <span class="task-result-title">${esc(d.title || d.id)}</span>
      ${elapsed ? `<span class="task-result-meta">${esc(elapsed)}</span>` : ''}
    </div>
    ${summaryBlock}
    ${actionsHtml}
    ${errBlock}`;
  return card;
}

function createPendingCard(p){
  const card = document.createElement('div');
  card.className = 'pending-card';
  const chips = (p.allowed_actions || []).map(a => `<span class="badge">${esc(a)}</span>`).join('');
  card.innerHTML = `
    <div class="pending-head">
      <span class="badge warn">⏳ Onay Bekliyor</span>
      <span class="pending-title">${esc(p.title || p.id)}</span>
    </div>
    <div class="pending-body">${esc(p.body_preview || '')}</div>
    ${chips ? `<div class="pending-chips">${chips}</div>` : ''}
    <div class="pending-actions">
      <button class="cancel-btn" data-pending="cancel">✕ İptal</button>
      <button class="confirm-btn" data-pending="confirm">✓ Onayla</button>
    </div>`;
  return card;
}

function render(){
  const hasAny = state.messages.length || state.pending.length || state.pendingTask || state.taskResults.length;
  emptyEl.style.display = hasAny ? 'none' : 'block';
  // Tüm dinamik içerik temizlenir; task-result-card'lar da dahil çünkü
  // sıralı yerleştirme için her render baştan kurulur.
  const existing = [...messagesEl.querySelectorAll('.bubble-row, .pending-card, .task-result-card')];
  existing.forEach(n => n.remove());

  const cards = [...state.taskResults].sort((a, b) => a.afterMessageCount - b.afterMessageCount);
  let cardIdx = 0;

  // Geçmiş mesajlar — her mesajdan sonra insertion point'i o sayıya denk
  // gelen kart varsa onu da bas.
  for (let i = 0; i < state.messages.length; i++){
    messagesEl.appendChild(createBubbleRow(state.messages[i]));
    while (cardIdx < cards.length && cards[cardIdx].afterMessageCount === i + 1){
      messagesEl.appendChild(createTaskResultCard(cards[cardIdx].data));
      cardIdx++;
    }
  }
  // Henüz history'e işlenmemiş insertion point > messages.length olanlar
  // (in-flight: kullanıcı onaylı, task hâlâ çalışıyor değil ama mesaj
  // henüz session'a düşmedi gibi rare durumlar için).
  while (cardIdx < cards.length){
    messagesEl.appendChild(createTaskResultCard(cards[cardIdx].data));
    cardIdx++;
  }
  // In-flight pending bubbles (user/thinking) ve aktif onay kartı
  for (const m of state.pending){
    messagesEl.appendChild(createBubbleRow(m));
  }
  if (state.pendingTask){
    messagesEl.appendChild(createPendingCard(state.pendingTask));
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-pending]');
  if (!btn || btn.disabled) return;
  const action = btn.dataset.pending;
  const allBtns = btn.parentElement.querySelectorAll('button');
  allBtns.forEach(b => b.disabled = true);
  const url = action === 'confirm' ? '/chat/confirm-pending' : '/chat/cancel-pending';
  try {
    const r = await fetch(url, {method:'POST'});
    if (!r.ok) {
      alert('Hata: HTTP ' + r.status);
      allBtns.forEach(b => b.disabled = false);
      return;
    }
    const data = await r.json();
    state.pendingTask = null;
    const ts = new Date().toLocaleTimeString();
    if (action === 'cancel'){
      state.pending = [{role:'agent', text:'✕ İptal edildi.', ts}];
      render();
      setTimeout(async () => {
        state.pending = [];
        await loadHistory();
        await loadSessions();
      }, 1200);
    } else {
      // confirm — thinking bubble bırak, task tamamlanana kadar poll et
      const thinkingBubble = {role:'agent', text:'✓ Onaylandı, çalışıyor…', thinking:true, ts};
      state.pending = [thinkingBubble];
      render();
      pollTaskUntilDone(data.task_id, thinkingBubble);
    }
  } catch (err) {
    alert('Bağlantı hatası: ' + err.message);
    allBtns.forEach(b => b.disabled = false);
  }
});

async function pollResultUpdate(taskId, entry){
  // loadHistory'den gelen henüz bitmemiş kart için — kart yerinde dururken
  // status güncellensin (thinking bubble yok bu yolda).
  for (let i = 0; i < 120; i++){
    await new Promise(r => setTimeout(r, 1500));
    try {
      const r = await fetch('/chat/task-status/' + encodeURIComponent(taskId), {cache:'no-store'});
      if (!r.ok) continue;
      const d = await r.json();
      entry.data = d;
      render();
      if (d.status === 'done' || d.status === 'failed') return;
    } catch(e) { /* transient */ }
  }
}

async function pollTaskUntilDone(taskId, thinkingBubble){
  const maxTries = 120;  // ~3 dakika
  for (let i = 0; i < maxTries; i++){
    await new Promise(r => setTimeout(r, 1500));
    try {
      const r = await fetch('/chat/task-status/' + encodeURIComponent(taskId), {cache:'no-store'});
      if (!r.ok) continue;
      const d = await r.json();
      if (d.status === 'done' || d.status === 'failed'){
        // Onay anındaki history boyutundan sonra ekle — bu, kullanıcının
        // onayladığı turn'in altına denk gelir; sonraki mesajlar bu kartın
        // altında akar, kart yukarı kaymaz.
        state.pending = state.pending.filter(m => m !== thinkingBubble);
        state.taskResults.push({
          afterMessageCount: state.messages.length,
          data: d,
        });
        render();
        return;
      }
      thinkingBubble.text = `⏳ Çalışıyor: ${d.title || taskId}…`;
      render();
    } catch(e) { /* transient */ }
  }
  thinkingBubble.text = '⏱ 3 dakika geçti — sonuç için Görevler sekmesine bak.';
  thinkingBubble.thinking = false;
  thinkingBubble.error = true;
  render();
}

function autosizeInput(){
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(160, inputEl.scrollHeight) + 'px';
}
inputEl.addEventListener('input', autosizeInput);
inputEl.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault();
    submitMessage();
  }
});
document.getElementById('chat-form').addEventListener('submit', (e) => {
  e.preventDefault();
  submitMessage();
});

picker.addEventListener('change', async () => {
  const sid = picker.value || null;
  await fetch('/chat/select', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sid})
  });
  state.session_id = sid;
  state.pending = [];
  state.taskResults = [];  // session değişti, yeni session'ın kartları loadHistory'de gelir
  await loadPendingTask();
  if (sid) {
    await loadHistory();
  } else {
    state.messages = [];
    render();
  }
});

resetBtn.addEventListener('click', async () => {
  if (!confirm('Bridge\\'in aktif oturumunu sıfırla?')) return;
  await fetch('/chat/reset', {method:'POST'});
  state.session_id = null;
  state.messages = [];
  state.pending = [];
  state.taskResults = [];
  await loadSessions();
  render();
});

async function submitMessage(){
  const text = inputEl.value.trim();
  if (!text) return;
  const ts = new Date().toLocaleTimeString();
  state.pending = [
    {role:'user', text, ts},
    {role:'agent', text:'Yazıyor…', thinking:true, ts:''}
  ];
  render();
  inputEl.value = '';
  autosizeInput();
  sendBtn.disabled = true;
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, admin_mode: adminMode})
    });
    if (!r.ok) {
      const errText = await r.text();
      state.pending[1] = {role:'agent', text:'Hata: HTTP ' + r.status + ' — ' + errText.slice(0,200), error:true, ts:new Date().toLocaleTimeString()};
      render();
    } else {
      const d = await r.json();
      // Bridge'ten history'i tekrar çek (ground truth jsonl'da)
      state.session_id = d.session_id;
      state.pendingTask = d.pending_task || null;
      state.pending = [];
      await loadHistory();
      // Picker'ı tazele — yeni session yaratıldıysa dropdown'a düşsün
      await loadSessions();
    }
  } catch (err) {
    state.pending[1] = {role:'agent', text:'Bağlantı hatası: ' + err.message, error:true, ts:new Date().toLocaleTimeString()};
    render();
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

(async () => {
  autosizeInput();
  await loadSessions();
  await loadHistory();
  await loadPendingTask();
  render();
})();
</script>
"""


@router.get("/panel/chat", response_class=HTMLResponse)
async def panel_chat():
    return HTMLResponse(_layout("Sohbet", "chat", _CHAT_BODY))


# ---------- /dashboard geriye uyum ----------

@router.get("/dashboard-legacy-redirect", include_in_schema=False)
async def _dummy():
    return {}


# ---------- /panel/events ----------

_EVENTS_BODY = """
<div class="row"><button onclick="reconnect()">Yeniden bağlan</button>
<span id="status" class="badge">bağlanıyor</span></div>
<div id="metrics" class="metrics-strip"></div>
<div id="events"></div>
<script>
let source = null;
function esc(s) { return String(s ?? "").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function serviceHtml(s) {
  const cls = s.ok ? 'ok' : 'err';
  const title = `${s.url||''} ${s.status ? 'HTTP ' + s.status : ''} ${s.error || ''} ${s.elapsed_ms ?? 0}ms`;
  return `<span class="service" title="${esc(title)}"><span class="dot ${cls}"></span>${esc(s.name)}</span>`;
}
function badgeForStatus(s) { return s === 'error' ? 'err' : (s === 'warn' ? 'warn' : 'ok'); }
function kindLabel(k){ return ({conversation:'Konuşma',task:'Görev',job:'Job',reset:'Reset',http:'HTTP'}[k]) || k; }

function quantile(arr, q){
  if (!arr.length) return null;
  const sorted = [...arr].sort((a,b)=>a-b);
  const idx = Math.min(sorted.length-1, Math.floor(q * (sorted.length-1)));
  return sorted[idx];
}
function fmtMs(ms){
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return ms + '<span class="metric-unit"> ms</span>';
  return (ms/1000).toFixed(1) + '<span class="metric-unit"> s</span>';
}
function statsForKind(events, kind, window){
  const items = events.filter(e => e.kind === kind && (e.elapsed_ms || 0) > 0).slice(0, window);
  if (!items.length) {
    return {count: 0, avg: null, p50: null, p95: null, errorPct: 0, recent: []};
  }
  const ms = items.map(e => e.elapsed_ms);
  const avg = Math.round(ms.reduce((a,b)=>a+b,0) / ms.length);
  const p50 = quantile(ms, 0.5);
  const p95 = quantile(ms, 0.95);
  const errors = items.filter(e => e.status === 'error').length;
  return {
    count: items.length,
    avg, p50, p95,
    errorPct: Math.round(100 * errors / items.length),
    recent: items.slice(0, 5).map(e => e.elapsed_ms),
  };
}
function renderMetrics(events){
  const config = [
    {kind:'conversation', label:'Konuşma', window: 20},
    {kind:'task', label:'Görev', window: 20},
    {kind:'job', label:'Job tick', window: 20},
  ];
  const html = config.map(c => {
    const s = statsForKind(events, c.kind, c.window);
    const sub = s.count
      ? `p50 ${fmtMs(s.p50)} · p95 ${fmtMs(s.p95)}${s.errorPct ? ' · ' + s.errorPct + '% hata' : ''}`
      : 'henüz tur yok';
    return `<div class="metric-card" data-kind="${c.kind}">
      <div class="metric-head">
        <span class="metric-title">${c.label}</span>
        <span class="metric-count">${s.count ? `son ${s.count}` : '—'}</span>
      </div>
      <div class="metric-big">${fmtMs(s.avg)}</div>
      <div class="metric-sub">${sub}</div>
    </div>`;
  }).join('');
  document.getElementById('metrics').innerHTML = html;
}
function renderEvents(events) {
  document.getElementById('events').innerHTML = events.length ? events.map(e => {
    const isErr = e.status === 'error';
    const replyOrErr = e.reply || e.error || '';
    const terminalCls = isErr ? 'ios-terminal err' : (replyOrErr ? 'ios-terminal' : 'ios-terminal empty');
    const replyContent = replyOrErr ? esc(replyOrErr) : '— yok';
    return `<div class="card ios-card">
      <div class="ios-head">
        <div>
          <div class="ios-title">${kindLabel(e.kind)}</div>
          <div class="ios-subtitle">${esc(e.ts)} · ${esc(e.agent || 'sistem')}</div>
        </div>
        <span class="badge ${badgeForStatus(e.status)}">${esc(e.status)}</span>
      </div>
      <div class="ios-section">
        <div class="ios-label">İstek</div>
        <div class="ios-body-text">${esc(e.text || '—')}</div>
      </div>
      <div class="ios-section">
        <div class="ios-label">${isErr ? 'Hata' : 'Yanıt'}</div>
        <div class="${terminalCls}">${replyContent}</div>
      </div>
      <div class="ios-chips">
        <span class="badge">${esc(e.elapsed_ms || 0)} ms</span>
        ${e.session ? `<span class="badge" title="session">${esc(e.session)}</span>` : ''}
      </div>
    </div>`;
  }).join('') : '<div class="empty">Henüz olay yok.</div>';
}
function renderServices(services) {
  document.getElementById('services').innerHTML = services.map(serviceHtml).join('');
}
function connect() {
  const status = document.getElementById('status');
  source = new EventSource('/events/stream');
  source.onopen = () => { status.textContent = 'canlı bağlı'; status.className = 'badge ok'; };
  source.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.type === 'events') {
      renderEvents(data.events || []);
      renderMetrics(data.events || []);
    }
    if (data.type === 'services') renderServices(data.services || []);
    status.textContent = 'canlı ' + new Date().toLocaleTimeString();
    status.className = 'badge ok';
  };
  source.onerror = () => { status.textContent = 'SSE yeniden bağlanıyor…'; status.className = 'badge err'; };
}
function reconnect() { if (source) source.close(); connect(); }
connect();
</script>
"""


@router.get("/panel/events", response_class=HTMLResponse)
async def panel_events():
    return HTMLResponse(_layout("Olaylar", "events", _EVENTS_BODY, with_services=True))


# ---------- /panel/tasks ----------

def _list_task_files() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"inbox": [], "processing": [], "done": [], "failed": []}
    for sub in out.keys():
        d = config.TASKS_DIR / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                text = p.read_text(encoding="utf-8")
                fm, body = frontmatter.parse(text)
            except Exception:
                fm, body = {}, ""
            first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
            out[sub].append({
                "name": p.name,
                "id": fm.get("id") or p.stem,
                "source": fm.get("source") or "-",
                "status": fm.get("status") or sub,
                "created": fm.get("created"),
                "started": fm.get("started_at"),
                "finished": fm.get("finished_at"),
                "elapsed_s": fm.get("elapsed_s"),
                "title": first_line[:160],
            })
    return out


_TASK_COLUMNS = [
    ("inbox", "Inbox"),
    ("processing", "İşleniyor"),
    ("done", "Tamamlandı"),
    ("failed", "Hatalı"),
]


@router.get("/panel/tasks/data")
async def panel_tasks_data():
    grouped = _list_task_files()
    return {
        "groups": [
            {"slug": slug, "label": label, "tasks": grouped.get(slug, [])}
            for slug, label in _TASK_COLUMNS
        ]
    }


@router.get("/panel/tasks/{subdir}/{name}/raw")
async def panel_task_raw(subdir: str, name: str):
    """Tek bir task'ın tam markdown içeriği — modal görüntüleyici için."""
    if subdir not in {"inbox", "processing", "done", "failed", "pending"}:
        raise HTTPException(400, f"geçersiz subdir: {subdir}")
    # path traversal guard
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "geçersiz dosya adı")
    path = config.TASKS_DIR / subdir / name
    if not path.exists() or not path.is_file():
        raise HTTPException(404, f"task bulunamadı: {subdir}/{name}")
    return {
        "subdir": subdir,
        "name": name,
        "size_bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "content": path.read_text(encoding="utf-8"),
    }


_TASKS_BODY = """
<div class="row"><span id="status" class="badge">canlı bağlanıyor…</span>
<small id="updated"></small></div>
<div id="board" class="board"></div>
<div class="task-modal-backdrop" id="task-modal-backdrop">
  <div class="task-modal" role="dialog" aria-modal="true">
    <div class="task-modal-head">
      <div>
        <div class="task-modal-title" id="task-modal-title">—</div>
        <div class="task-modal-meta" id="task-modal-meta"></div>
      </div>
      <button class="task-modal-close" id="task-modal-close" type="button">✕ Kapat</button>
    </div>
    <div class="task-modal-body">
      <pre id="task-modal-content">yükleniyor…</pre>
    </div>
  </div>
</div>
<script>
const COLS = [
  {slug:'inbox', label:'Inbox'},
  {slug:'processing', label:'İşleniyor'},
  {slug:'done', label:'Tamamlandı'},
  {slug:'failed', label:'Hatalı'}
];
function esc(s){return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function renderCard(subdir, t){
  const showButtons = subdir !== 'processing';
  const buttons = showButtons ? `<div class="ios-actions">
    <button data-action="rerun" data-subdir="${esc(subdir)}" data-name="${esc(t.name)}">↻ Tekrar</button>
    <button class="danger" data-action="delete" data-subdir="${esc(subdir)}" data-name="${esc(t.name)}">✕ Sil</button>
  </div>` : '';
  const elapsedChip = t.elapsed_s ? `<span class="badge">${t.elapsed_s}s</span>` : '';
  const createdChip = t.created ? `<span class="badge" title="created">${esc(t.created)}</span>` : '';
  return `<div class="card ios-card clickable" data-open-task="${esc(subdir)}/${esc(t.name)}" title="Tam içeriği gör">
    <div class="ios-head">
      <div class="ios-title">${esc(t.id)}</div>
      ${buttons}
    </div>
    <div class="ios-section">
      <div class="ios-label">Görev</div>
      <div class="ios-body-text">${esc(t.title || '')}</div>
    </div>
    <div class="ios-chips">
      <span class="badge">${esc(t.source || '-')}</span>
      ${elapsedChip}
      ${createdChip}
    </div>
  </div>`;
}

// ---- Modal: tam task içeriği ----
const modal = document.getElementById('task-modal-backdrop');
const modalTitle = document.getElementById('task-modal-title');
const modalMeta = document.getElementById('task-modal-meta');
const modalContent = document.getElementById('task-modal-content');
async function openTaskModal(subdir, name){
  modalTitle.textContent = name;
  modalMeta.textContent = subdir;
  modalContent.textContent = 'yükleniyor…';
  modal.classList.add('open');
  try {
    const r = await fetch(`/panel/tasks/${encodeURIComponent(subdir)}/${encodeURIComponent(name)}/raw`, {cache:'no-store'});
    if (!r.ok){ modalContent.textContent = 'Hata: HTTP ' + r.status; return; }
    const d = await r.json();
    modalContent.textContent = d.content || '(boş)';
    modalMeta.textContent = `${d.subdir} · ${Math.round((d.size_bytes||0)/1024*10)/10} kb`;
  } catch(e){ modalContent.textContent = 'Bağlantı hatası: ' + e.message; }
}
function closeTaskModal(){ modal.classList.remove('open'); }
modal.addEventListener('click', (e) => { if (e.target === modal) closeTaskModal(); });
document.getElementById('task-modal-close').addEventListener('click', closeTaskModal);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && modal.classList.contains('open')) closeTaskModal(); });

async function loadAndRender(){
  try {
    const r = await fetch('/panel/tasks/data', {cache:'no-store'});
    const d = await r.json();
    const root = document.getElementById('board');
    root.innerHTML = d.groups.map(g => `
      <div class="col" data-status="${g.slug}">
        <div class="col-head">
          <span>${g.label}</span>
          <span class="badge">${g.tasks.length}</span>
        </div>
        <div class="col-body">
          ${g.tasks.length ? g.tasks.map(t => renderCard(g.slug, t)).join('') : '<div class="empty">boş</div>'}
        </div>
      </div>`).join('');
    document.getElementById('updated').textContent =
      'son güncel ' + new Date().toLocaleTimeString();
  } catch (e) {
    console.error(e);
  }
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (btn){
    // Aksiyon butonlarına özel — kart açma event'ini tetiklemesin
    e.stopPropagation();
    const subdir = btn.dataset.subdir;
    const name = btn.dataset.name;
    const action = btn.dataset.action;
    if (action === 'delete' && !confirm('Görev silinsin mi: ' + name + '?')) return;
    const r = await fetch(`/panel/tasks/${encodeURIComponent(subdir)}/${encodeURIComponent(name)}/${action}`, {method:'POST'});
    if (!r.ok) { alert('Hata: ' + r.status); return; }
    loadAndRender();
    return;
  }
  const cardTrigger = e.target.closest('[data-open-task]');
  if (cardTrigger){
    const [subdir, name] = cardTrigger.dataset.openTask.split('/');
    if (subdir && name) openTaskModal(subdir, name);
  }
});

// SSE: task event geldiğinde tahta otomatik yenilenir
let source = null;
let lastTaskTs = '';
function connectSSE(){
  const status = document.getElementById('status');
  source = new EventSource('/events/stream');
  source.onopen = () => { status.textContent = 'canlı bağlı'; status.className = 'badge ok'; };
  source.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      if (d.type !== 'events') return;
      // En son task event'inin timestamp'i değiştiyse refresh et
      const latestTask = (d.events || []).find(e => e.kind === 'task');
      if (latestTask && latestTask.ts !== lastTaskTs) {
        lastTaskTs = latestTask.ts;
        loadAndRender();
      } else if (lastTaskTs === '') {
        // ilk bağlantıda hep yenile
        lastTaskTs = latestTask ? latestTask.ts : 'init';
        loadAndRender();
      }
    } catch (e) { console.error(e); }
  };
  source.onerror = () => {
    status.textContent = 'SSE yeniden bağlanıyor…';
    status.className = 'badge err';
  };
}

loadAndRender();
connectSSE();
// Güvenlik ağı: 10sn'de bir hafif refresh (SSE kaçırırsa)
setInterval(loadAndRender, 10000);
</script>
"""


@router.get("/panel/tasks", response_class=HTMLResponse)
async def panel_tasks():
    return HTMLResponse(_layout("Görevler", "tasks", _TASKS_BODY))


@router.post("/panel/tasks/{subdir}/{name}/rerun")
async def task_rerun(subdir: str, name: str):
    if subdir not in ("inbox", "processing", "done", "failed"):
        raise HTTPException(400, "geçersiz alt klasör")
    src = config.TASKS_DIR / subdir / name
    if not src.exists():
        raise HTTPException(404, "task bulunamadı")
    target = config.TASKS_DIR / "inbox" / name
    if subdir == "inbox":
        # touch to retrigger watcher
        src.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        # status'u reset edip inbox'a taşı
        text = src.read_text(encoding="utf-8")
        fm, body = frontmatter.parse(text)
        fm["status"] = "pending"
        fm["retry_count"] = int(fm.get("retry_count") or 0) + 1
        for k in ("started_at", "finished_at", "elapsed_s", "error"):
            fm.pop(k, None)
        # Result section'larını kırp — body içinde "## " ile başlayanları kes
        clean_body_lines: list[str] = []
        for line in body.splitlines():
            if line.startswith("## "):
                break
            clean_body_lines.append(line)
        target.write_text(frontmatter.render(fm, "\n".join(clean_body_lines).rstrip() + "\n"), encoding="utf-8")
        src.unlink()
    return {"status": "ok"}


@router.post("/panel/tasks/{subdir}/{name}/delete")
async def task_delete(subdir: str, name: str):
    if subdir not in ("inbox", "processing", "done", "failed"):
        raise HTTPException(400, "geçersiz alt klasör")
    src = config.TASKS_DIR / subdir / name
    if not src.exists():
        raise HTTPException(404, "task bulunamadı")
    src.unlink()
    return {"status": "ok"}


# ---------- /panel/jobs ----------

_JOBS_BODY = """
<div class="row"><span id="status" class="badge">canlı bağlanıyor…</span>
<small id="updated"></small></div>
<div id="board" class="board two"><div class="empty">Yükleniyor…</div></div>
<script>
function esc(s){return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function renderJobCard(j){
  const status = j.last_status === 'ok' ? 'ok' : (j.last_status ? 'err' : 'warn');
  const enabled = j.enabled !== false;
  const installedBadge = enabled
    ? `<span class="badge ${j.installed ? 'ok' : 'err'}">${j.installed ? 'kuruldu' : 'kurulu değil'}</span>`
    : `<span class="badge warn">durduruldu</span>`;
  const toggleBtn = enabled
    ? `<button data-action="disable" data-id="${esc(j.id)}">⏸ Pasif et</button>`
    : `<button data-action="enable" data-id="${esc(j.id)}">▶ Aktif et</button>`;
  const terminalContent = j.last_summary
    ? esc(j.last_summary)
    : '<span class="empty">— henüz çalışmadı</span>';
  return `<div class="card ios-card">
    <div class="ios-head">
      <div class="ios-title">${esc(j.id)}</div>
      <div class="ios-actions">
        <button data-action="run" data-id="${esc(j.id)}" ${enabled ? '' : 'disabled'}>▶ Çalıştır</button>
        ${toggleBtn}
        <button class="danger" data-action="delete" data-id="${esc(j.id)}">✕ Sil</button>
      </div>
    </div>
    <div class="ios-section">
      <div class="ios-label">Action</div>
      <div class="ios-value">${esc(j.action_type || '-')}</div>
    </div>
    <div class="ios-section">
      <div class="ios-label">Sonuç</div>
      <div class="ios-terminal${j.last_summary ? '' : ' empty'}">${terminalContent}</div>
    </div>
    <div class="ios-chips">
      <span class="badge">${esc(j.schedule)}</span>
      <span class="badge">runs: ${j.runs}</span>
      ${installedBadge}
      <span class="badge ${status}">${esc(j.last_status || '-')}</span>
      ${j.last_run ? `<span class="badge" title="last_run">${esc(j.last_run)}</span>` : ''}
    </div>
  </div>`;
}

async function load(){
  try {
    const r = await fetch('/agent/jobs', {cache:'no-store'});
    const d = await r.json();
    const active = (d.jobs || []).filter(j => j.enabled !== false);
    const paused = (d.jobs || []).filter(j => j.enabled === false);
    const root = document.getElementById('board');
    root.innerHTML = [
      {slug:'active', label:'Aktif', items: active},
      {slug:'paused', label:'Durduruldu', items: paused}
    ].map(g => `
      <div class="col" data-status="${g.slug}">
        <div class="col-head">
          <span>${g.label}</span>
          <span class="badge">${g.items.length}</span>
        </div>
        <div class="col-body">
          ${g.items.length ? g.items.map(renderJobCard).join('') : '<div class="empty">boş</div>'}
        </div>
      </div>`).join('');
    document.getElementById('updated').textContent =
      'son güncel ' + new Date().toLocaleTimeString();
  } catch (e) { console.error(e); }
}

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn || btn.disabled) return;
  const id = btn.dataset.id;
  const action = btn.dataset.action;
  let url = '/agent/jobs/' + encodeURIComponent(id);
  let method = 'POST';
  if (action === 'run') url += '/run';
  else if (action === 'disable') url += '/disable';
  else if (action === 'enable') url += '/enable';
  else if (action === 'delete') {
    if (!confirm('Job silinsin mi: ' + id + '?')) return;
    method = 'DELETE';
  } else return;
  const r = await fetch(url, {method});
  if (!r.ok) { alert('Hata: ' + r.status); return; }
  load();
});

// SSE: job/scheduler event geldiğinde tabloyu otomatik yenile
let source = null;
let lastJobTs = '';
function connectSSE(){
  const status = document.getElementById('status');
  source = new EventSource('/events/stream');
  source.onopen = () => { status.textContent = 'canlı bağlı'; status.className = 'badge ok'; };
  source.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      if (d.type !== 'events') return;
      const latestJob = (d.events || []).find(e => e.kind === 'job');
      if (latestJob && latestJob.ts !== lastJobTs) {
        lastJobTs = latestJob.ts;
        load();
      }
    } catch (e) { console.error(e); }
  };
  source.onerror = () => {
    status.textContent = 'SSE yeniden bağlanıyor…';
    status.className = 'badge err';
  };
}

load();
connectSSE();
// Güvenlik ağı: 8sn'de bir yenile (SSE kaçırırsa)
setInterval(load, 8000);
</script>
"""


@router.get("/panel/jobs", response_class=HTMLResponse)
async def panel_jobs():
    return HTMLResponse(_layout("Job'lar", "jobs", _JOBS_BODY))


# ---------- /panel/sessions ----------

def _summarize_session(p: Path) -> dict:
    info: dict = {"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1), "agent": None, "first_user": None, "messages": 0}
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                t = obj.get("type")
                if t == "message":
                    info["messages"] += 1
                    if obj.get("role") == "user" and info["first_user"] is None:
                        content = obj.get("content")
                        if isinstance(content, list) and content:
                            first = content[0]
                            if isinstance(first, dict):
                                info["first_user"] = first.get("text") or first.get("content") or ""
                        elif isinstance(content, str):
                            info["first_user"] = content
    except Exception:
        pass
    return info


@router.get("/panel/sessions", response_class=HTMLResponse)
async def panel_sessions():
    rows_personas: list[str] = []
    persona_dirs = {
        "voice_bridge/agents": config.CORE_DIR / "voice_bridge" / "agents",
        "autonomous/personas": config.CORE_DIR / "autonomous" / "personas",
    }
    for label, d in persona_dirs.items():
        if not d.exists():
            continue
        for p in sorted(d.glob("*.md")):
            stat = p.stat()
            try:
                fm, _ = frontmatter.parse(p.read_text(encoding="utf-8"))
            except Exception:
                fm = {}
            triggers = fm.get("triggers")
            if isinstance(triggers, list) and triggers:
                trigger_chips = "".join(
                    f'<span class="badge">{html.escape(t)}</span>' for t in triggers
                )
                trigger_block = f'<div class="ios-section"><div class="ios-label">Triggers</div><div class="ios-chips" style="margin-top:0;padding-top:0;border:none">{trigger_chips}</div></div>'
            else:
                trigger_block = '<div class="ios-section"><div class="ios-label">Triggers</div><div class="ios-body-text" style="color:#5a6172">— yok</div></div>'
            rows_personas.append(f"""
            <div class="card ios-card">
              <div class="ios-head">
                <div>
                  <div class="ios-title">{html.escape(p.stem)}</div>
                  <div class="ios-subtitle">{html.escape(label)}/{html.escape(p.name)}</div>
                </div>
              </div>
              {trigger_block}
              <div class="ios-chips">
                <span class="badge">{round(stat.st_size/1024,1)} kb</span>
              </div>
            </div>""")

    rows_sessions: list[str] = []
    if config.SESSION_DIR.exists():
        for p in sorted(config.SESSION_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)[:50]:
            info = _summarize_session(p)
            preview = (info.get("first_user") or "").strip()[:240]
            # Filename can be long timestamp+uuid; show first 24 chars + last 4 for readability
            short = p.stem
            if len(short) > 36:
                short = short[:24] + "…" + short[-8:]
            preview_block = (
                f'<div class="ios-terminal">{html.escape(preview)}</div>'
                if preview
                else '<div class="ios-terminal empty">— ilk mesaj okunamadı</div>'
            )
            rows_sessions.append(f"""
            <div class="card ios-card">
              <div class="ios-head">
                <div class="ios-title">{html.escape(short)}</div>
              </div>
              <div class="ios-section">
                <div class="ios-label">İlk Mesaj</div>
                {preview_block}
              </div>
              <div class="ios-chips">
                <span class="badge">{info["messages"]} msg</span>
                <span class="badge">{info["size_kb"]} kb</span>
              </div>
            </div>""")

    body = (
        '<h2 style="font-size:13px;color:#8a92a3;text-transform:uppercase;letter-spacing:.06em;margin:6px 0 10px">Persona dosyaları</h2>'
        + ("".join(rows_personas) or '<div class="empty">Persona bulunamadı.</div>')
        + '<h2 style="font-size:13px;color:#8a92a3;text-transform:uppercase;letter-spacing:.06em;margin:24px 0 10px">Son Pi oturumları (en fazla 50)</h2>'
        + ("".join(rows_sessions) or '<div class="empty">Henüz Pi oturumu yok.</div>')
    )
    return HTMLResponse(_layout("Oturumlar", "sessions", body))


# ---------- /panel/users ----------

@router.get("/panel/users", response_class=HTMLResponse)
async def panel_users():
    setup = auth.setup_required()
    users = auth.list_users()
    cur = (auth.current_user() or {}).get("username")

    if setup:
        banner = """
<div class="setup-banner">
  <h3>Setup gerek</h3>
  <p>Henüz kayıtlı kullanıcı yok. Aşağıdaki formdan ilk kullanıcıyı ekle — otomatik admin olur ve aktif kullanıcı olarak işaretlenir.</p>
</div>"""
    else:
        banner = ""

    rows: list[str] = []
    for u in users:
        username = u.get("username", "")
        is_admin_user = bool(u.get("admin"))
        is_active = (username == cur)
        created = (u.get("created") or "")[:10]  # YYYY-MM-DD
        active_badge = (
            '<span class="badge ok" style="font-size:10.5px">✓ Aktif</span>'
            if is_active else ""
        )
        rows.append(f"""
<div class="card ios-card" data-username="{html.escape(username)}">
  <div class="user-card-row">
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <div class="ios-title" style="font-size:16px">👤 {html.escape(username)}</div>
      {active_badge}
    </div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <label class="admin-toggle" style="cursor:pointer">
        <input type="checkbox" data-admin-toggle="{html.escape(username)}" {"checked" if is_admin_user else ""} style="margin:0">
        Admin
      </label>
      {'' if is_active else f'<button data-action="login" data-user="{html.escape(username)}">Giriş yap</button>'}
      <button class="danger" data-action="delete" data-user="{html.escape(username)}">✕ Sil</button>
    </div>
  </div>
  <div class="ios-chips" style="margin-top:6px;padding-top:8px">
    <span class="badge">created {html.escape(created or "—")}</span>
    {('<span class="badge" style="background:#3a2c1a;color:#ffd485">🛡 admin</span>' if is_admin_user else '')}
  </div>
</div>""")

    form_html = """
<div class="user-card-form" style="margin-top:10px">
  <input id="new-username" placeholder="yeni kullanıcı (örn. doktor)" autocomplete="off">
  <label style="display:inline-flex;align-items:center;gap:5px;font-size:12px;color:#cdd6e3">
    <input type="checkbox" id="new-admin"> Admin
  </label>
  <button id="add-user-btn">+ Ekle</button>
</div>"""

    body = (
        banner
        + '<h2 style="font-size:13px;color:#8a92a3;text-transform:uppercase;letter-spacing:.06em;margin:6px 0 10px">Kullanıcılar</h2>'
        + ("".join(rows) or '<div class="empty">Henüz kullanıcı yok.</div>')
        + '<h2 style="font-size:13px;color:#8a92a3;text-transform:uppercase;letter-spacing:.06em;margin:24px 0 10px">Yeni kullanıcı</h2>'
        + form_html
        + """
<script>
(function(){
  function $(s){return document.querySelector(s)}
  async function postJSON(url, body, method){
    const r = await fetch(url, {method: method || 'POST', headers:{'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : null});
    if (!r.ok){
      let msg = 'HTTP ' + r.status;
      try { const d = await r.json(); if (d.detail) msg = d.detail; } catch(e){}
      throw new Error(msg);
    }
    return r.json();
  }
  document.addEventListener('change', async (e) => {
    const cb = e.target.closest('[data-admin-toggle]');
    if (!cb) return;
    const username = cb.dataset.adminToggle;
    const admin = cb.checked;
    try {
      await postJSON('/auth/users/' + encodeURIComponent(username), {admin}, 'PATCH');
    } catch(err){
      cb.checked = !admin;
      alert('Admin değiştirilemedi: ' + err.message);
    }
  });
  document.addEventListener('click', async (e) => {
    const addBtn = e.target.closest('#add-user-btn');
    if (addBtn){
      const username = $('#new-username').value.trim();
      const admin = $('#new-admin').checked;
      if (!username) { alert('username boş olmaz'); return; }
      try {
        await postJSON('/auth/users', {username, admin});
        location.reload();
      } catch(err){ alert('Hata: ' + err.message); }
      return;
    }
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const user = btn.dataset.user;
    if (action === 'delete'){
      if (!confirm('Sil: ' + user + ' ?')) return;
      try {
        await postJSON('/auth/users/' + encodeURIComponent(user), null, 'DELETE');
        location.reload();
      } catch(err){ alert('Hata: ' + err.message); }
    } else if (action === 'login'){
      try {
        await postJSON('/auth/login', {username: user});
        location.reload();
      } catch(err){ alert('Hata: ' + err.message); }
    }
  });
})();
</script>
"""
    )
    return HTMLResponse(_layout("Kullanıcılar", "users", body))
