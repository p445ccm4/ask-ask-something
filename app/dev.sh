#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
if [[ -d "/opt/micromamba/bin" ]] && [[ ":$PATH:" != *":/opt/micromamba/bin:"* ]]; then
  export PATH="$PATH:/opt/micromamba/bin"
fi

"$APP_DIR/setup_mounts.sh"

AGENT_PORT="${AGENT_SERVICE_PORT:-8000}"
WEB_PORT="${PORT:-3000}"

if [[ -z "${NEXT_PUBLIC_BASE_PATH+x}" ]]; then
  if [[ "${CLOUD_SHELL:-}" == "true" ]]; then
    NEXT_PUBLIC_BASE_PATH=""
  elif [[ "${IS_WORKBENCH_IMAGE:-}" == "true" ]] \
    || [[ "${VERTEX_PRODUCT:-}" == "WORKBENCH_INSTANCE" ]] \
    || [[ -n "${JUPYTER_SERVER_ROOT:-}${JUPYTER_SERVER_URL:-}${JUPYTER_RUNTIME_DIR:-}${JPY_PARENT_PID:-}${DL_ANACONDA_HOME:-}" ]] \
    || [[ "${HOME:-}" == "/home/jupyter" ]] \
    || [[ -d "/opt/deeplearning" ]] \
    || [[ -f "/etc/jupyter/jupyter_server_config.py" ]] \
    || [[ -f "/etc/jupyter/jupyter_notebook_config.py" ]]; then
    NEXT_PUBLIC_BASE_PATH="/proxy/absolute/${WEB_PORT}"
  else
    NEXT_PUBLIC_BASE_PATH=""
  fi
fi
NEXT_PUBLIC_BASE_PATH="${NEXT_PUBLIC_BASE_PATH%/}"
export NEXT_PUBLIC_BASE_PATH

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
  PYTHONPATH="$APP_DIR/agent-service/src:$APP_DIR/vendor/antigravity-workbench/backend/src${PYTHONPATH:+:$PYTHONPATH}" \
    UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --no-sync uvicorn ask_workbench.main:app \
    --host 127.0.0.1 \
    --port "$AGENT_PORT" \
    --reload
) &
AGENT_PID=$!

echo "[AskAsk* Workbench] Starting Next.js UI + BFF on http://0.0.0.0:${WEB_PORT}${NEXT_PUBLIC_BASE_PATH} ..."
(
  cd "$APP_DIR/web"
  AGENT_SERVICE_URL="http://127.0.0.1:${AGENT_PORT}" \
    NEXT_PUBLIC_BASE_PATH="$NEXT_PUBLIC_BASE_PATH" \
    npm run dev -- --hostname 0.0.0.0 --port "$WEB_PORT"
) &
WEB_PID=$!

wait -n "$AGENT_PID" "$WEB_PID"
