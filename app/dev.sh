#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$APP_DIR/setup_mounts.sh"

AGENT_PORT="${AGENT_SERVICE_PORT:-8000}"
WEB_PORT="${PORT:-3000}"

cleanup() {
  echo ""
  echo "[AskAsk* Workbench] Shutting down services..."
  [[ -n "${AGENT_PID:-}" ]] && kill "$AGENT_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[AskAsk* Workbench] Starting FastAPI + Antigravity service on http://127.0.0.1:${AGENT_PORT} ..."
(
  cd "$APP_DIR/agent-service"
  UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run uvicorn ask_workbench.main:app \
    --host 127.0.0.1 \
    --port "$AGENT_PORT" \
    --reload
) &
AGENT_PID=$!

echo "[AskAsk* Workbench] Starting Next.js UI + BFF on http://0.0.0.0:${WEB_PORT} ..."
(
  cd "$APP_DIR/web"
  AGENT_SERVICE_URL="http://127.0.0.1:${AGENT_PORT}" npm run dev -- --hostname 0.0.0.0 --port "$WEB_PORT"
) &
WEB_PID=$!

wait -n "$AGENT_PID" "$WEB_PID"
