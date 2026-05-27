"""Mate Core — platform-agnostik path ve runtime ayarları.

Tüm runtime dosyaları (state, sessions, Pi HOME izolasyonu, bundled binary)
`mate-core/` altında tutulur — Mac/Ubuntu fark etmez, repo'yla birlikte taşınır.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

SYSTEM = platform.system()  # 'Darwin' | 'Linux'

# Repo içi paths — mate-core dizini (bu dosyanın iki üst klasörü)
CORE_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = CORE_DIR / "voice_bridge" / "agents"
TASKS_DIR = CORE_DIR / "tasks"  # Faz 3+ için (inbox/, processing/, done/, failed/)

# Pi Agent'ın HOME'u — settings/extensions/skills/memory-vault burada, global
# `~/.pi/` ile karışmaz. caller.py subprocess'e HOME=PI_HOME geçer.
PI_HOME = CORE_DIR / ".pi-home"

# Token (LAN dashboard auth, .token tek satır plaintext)
TOKEN_FILE = CORE_DIR / ".token"
TOKEN = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""

# Pi Agent binary — env override > bundled local > platform default fallback
def pi_bin() -> Path:
    env = os.environ.get("MATE_PI_BIN")
    if env:
        return Path(env)
    local = CORE_DIR / "node_modules" / ".bin" / "pi"
    if local.exists():
        return local
    # Fallback: dev'de bundle yapmadan test için global'e düş
    if SYSTEM == "Darwin":
        return Path("/opt/homebrew/bin/pi")
    return Path("/usr/local/bin/pi")


PI_BIN = pi_bin()

# Pi defaults — Pi'nin global default'u (google) yerine Codex Plus aboneliği
PI_PROVIDER = os.environ.get("MATE_PI_PROVIDER", "openai-codex")
PI_MODEL = os.environ.get("MATE_PI_MODEL", "gpt-5.5")
PI_THINKING = os.environ.get("MATE_PI_THINKING", "low")

# Voice persona — frontmatter trigger eşleşmesi olmazsa fallback
DEFAULT_AGENT = os.environ.get("MATE_PI_AGENT", "voice-default")

# STT/TTS cloud servisleri (dashboard health pulse + iOS health check)
STT_BASE_URL = os.environ.get("MATE_STT_URL", "https://stt.drascom.uk").rstrip("/")
TTS_BASE_URL = os.environ.get("MATE_TTS_URL", "https://tts.drascom.uk").rstrip("/")
SERVICE_CHECK_TIMEOUT_SEC = 3

# Pi subprocess timeout (chat round-trip)
# 60'tan 120'ye çıkardık: uzun session resume'larında Pi context okuması
# saniyeler alabiliyor; özellikle agent-builder gibi büyük persona prompt'larıyla.
TIMEOUT_SEC = 120


def state_dir() -> Path:
    """Mate runtime state — locks, retry counters, job index'leri, log'lar.
    mate-core/state altında — Mac/Ubuntu fark etmez, repo'yla taşınır."""
    return CORE_DIR / "state"


def session_dir() -> Path:
    """Pi'nin --session-dir argümanı — her chat jsonl olarak burada."""
    return state_dir() / "sessions"


# Boot-time: state, session ve Pi HOME dizinlerini garanti et
STATE_DIR = state_dir()
STATE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR = session_dir()
SESSION_DIR.mkdir(parents=True, exist_ok=True)
(PI_HOME / ".pi" / "agent").mkdir(parents=True, exist_ok=True)

# Server bind
HOST = os.environ.get("MATE_CORE_HOST", "0.0.0.0")
PORT = int(os.environ.get("MATE_CORE_PORT", "8643"))
