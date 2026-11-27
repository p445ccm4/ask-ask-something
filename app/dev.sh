#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AG_LOG_PREFIX="[AskAsk* Workbench]"
ARTIFACT_REGISTRY_SCRIPT="$APP_DIR/vendor/antigravity-workbench/scripts/artifact_registry.sh"
if [[ ! -f "$ARTIFACT_REGISTRY_SCRIPT" ]]; then
  echo "[AskAsk* Workbench] Error: missing $ARTIFACT_REGISTRY_SCRIPT (run 'git submodule update --init --recursive')." >&2
  exit 1
fi
# shellcheck source=vendor/antigravity-workbench/scripts/artifact_registry.sh
source "$ARTIFACT_REGISTRY_SCRIPT"

ag_ensure_user_bin_path
"$APP_DIR/setup_mounts.sh"

AGENT_PORT="${AGENT_SERVICE_PORT:-8000}"
WEB_PORT="${PORT:-3000}"

if [[ -z "${NEXT_PUBLIC_BASE_PATH+x}" ]]; then
  if [[ "${CLOUD_SHELL:-}" == "true" ]]; then
    NEXT_PUBLIC_BASE_PATH=""
  elif is_google_cloud_workbench; then
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
