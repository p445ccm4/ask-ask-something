#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKIP_BUILD=false
for arg in "$@"; do
  case "$arg" in
    --no-build)
      SKIP_BUILD=true
      ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--no-build]"
      echo ""
      echo "Start AskAsk* Workbench in production mode (no hot-reload)."
      echo "  --no-build   Skip 'npm run build' if app/web/.next is already built."
      echo ""
      echo "Environment overrides:"
      echo "  PORT                 Next.js port (default: 3000)"
      echo "  AGENT_SERVICE_PORT   FastAPI backend port (default: 8000)"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Run '$(basename "$0") --help' for usage." >&2
      exit 1
      ;;
  esac
done

"$APP_DIR/setup_mounts.sh"

AGENT_PORT="${AGENT_SERVICE_PORT:-8000}"
WEB_PORT="${PORT:-3000}"

if [[ -z "${NEXT_PUBLIC_BASE_PATH+x}" ]]; then
  if [[ "${CLOUD_SHELL:-}" == "true" ]]; then
    NEXT_PUBLIC_BASE_PATH=""
  elif [[ -n "${JUPYTER_SERVER_ROOT:-}${JUPYTER_SERVER_URL:-}${JUPYTER_RUNTIME_DIR:-}${JPY_PARENT_PID:-}${DL_ANACONDA_HOME:-}" ]] \
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

if [[ "$SKIP_BUILD" == "false" ]]; then
  echo "[AskAsk* Workbench] Building Next.js production bundle..."
  (
    cd "$APP_DIR/web"
    NEXT_PUBLIC_BASE_PATH="$NEXT_PUBLIC_BASE_PATH" npm run build
  )
elif [[ ! -f "$APP_DIR/web/.next/BUILD_ID" ]]; then
  echo "[AskAsk* Workbench] Error: --no-build specified, but web/.next/BUILD_ID was not found." >&2
  echo "Run ./app/prod.sh without --no-build first." >&2
  exit 1
fi

cleanup() {
  echo ""
  echo "[AskAsk* Workbench] Shutting down services..."
  [[ -n "${AGENT_PID:-}" ]] && kill "$AGENT_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[AskAsk* Workbench] Starting FastAPI + Antigravity service (prod) on http://127.0.0.1:${AGENT_PORT} ..."
(
  cd "$APP_DIR/agent-service"
  exec env PYTHONPATH="$APP_DIR/agent-service/src:$APP_DIR/vendor/antigravity-workbench/backend/src${PYTHONPATH:+:$PYTHONPATH}" \
    UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run --no-sync uvicorn ask_workbench.main:app \
    --host 127.0.0.1 \
    --port "$AGENT_PORT"
) &
AGENT_PID=$!

echo "[AskAsk* Workbench] Starting Next.js UI + BFF (prod) on http://0.0.0.0:${WEB_PORT}${NEXT_PUBLIC_BASE_PATH} ..."
(
  cd "$APP_DIR/web"
  exec env AGENT_SERVICE_URL="http://127.0.0.1:${AGENT_PORT}" \
    NEXT_PUBLIC_BASE_PATH="$NEXT_PUBLIC_BASE_PATH" \
    npm run start -- --hostname 0.0.0.0 --port "$WEB_PORT"
) &
WEB_PID=$!

wait -n "$AGENT_PID" "$WEB_PID"
