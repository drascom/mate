#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[mate-core] .venv bulunamadı, oluşturuluyor..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if [ ! -x "node_modules/.bin/pi" ]; then
  echo "[mate-core] Pi binary bulunamadı, npm install çalışıyor..."
  if ! command -v npm >/dev/null 2>&1; then
    echo "[mate-core] HATA: npm bulunamadı. node + npm kurulu olmalı." >&2
    exit 1
  fi
  npm install --no-audit --no-fund --silent
fi

python - <<'PY'
import importlib.util
import subprocess
import sys

required = ("fastapi", "uvicorn", "pydantic", "watchfiles")
missing = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]
if missing:
    print("[mate-core] Eksik paketler kuruluyor:", ", ".join(missing))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn[standard]", "pydantic", "watchfiles"])
PY

PORT="${MATE_CORE_PORT:-8643}"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo 127.0.0.1)"
EXISTING_PIDS="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"

if [ -n "${EXISTING_PIDS}" ]; then
  echo "[mate-core] ${PORT} portu zaten kullanımda."
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN || true
  echo
  if [ "${1:-}" = "--kill" ]; then
    echo "[mate-core] Eski process durduruluyor: ${EXISTING_PIDS}"
    kill ${EXISTING_PIDS}
    sleep 1
  else
    echo "[mate-core] Zaten çalışan core olabilir."
    echo "[mate-core] Local:     http://127.0.0.1:${PORT}"
    echo "[mate-core] LAN:       http://${LAN_IP}:${PORT}"
    echo "[mate-core] Dashboard: http://127.0.0.1:${PORT}/dashboard"
    echo
    echo "[mate-core] Yeniden başlatmak için: ./run.sh --kill"
    exit 0
  fi
fi

echo "[mate-core] ${PORT} üzerinde başlatılıyor."
echo "[mate-core] Local:     http://127.0.0.1:${PORT}"
echo "[mate-core] LAN:       http://${LAN_IP}:${PORT}"
echo "[mate-core] Dashboard: http://127.0.0.1:${PORT}/dashboard"
export MATE_CORE_PORT="${PORT}"
exec python main.py
