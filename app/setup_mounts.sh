#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$APP_DIR/agent-service"
WEB_DIR="$APP_DIR/web"

echo "[AskAsk* Workbench] Ensuring /tmp bind mounts for low-disk Cloud Shell compliance..."

mkdir -p /tmp/xdg-cache /tmp/npm-cache /tmp/uv-python "$HOME/.cache" "$HOME/.npm"
chmod 700 /tmp/xdg-cache "$HOME/.cache"
mountpoint -q "$HOME/.cache" || sudo mount --bind /tmp/xdg-cache "$HOME/.cache"
mountpoint -q "$HOME/.npm" || sudo mount --bind /tmp/npm-cache "$HOME/.npm"

mkdir -p /tmp/ask-workbench-agent-venv "$AGENT_DIR/.venv"
mountpoint -q "$AGENT_DIR/.venv" || sudo mount --bind /tmp/ask-workbench-agent-venv "$AGENT_DIR/.venv"

mkdir -p /tmp/ask-workbench-web-node_modules "$WEB_DIR/node_modules"
mkdir -p /tmp/ask-workbench-web-next "$WEB_DIR/.next"
mountpoint -q "$WEB_DIR/node_modules" || sudo mount --bind /tmp/ask-workbench-web-node_modules "$WEB_DIR/node_modules"
mountpoint -q "$WEB_DIR/.next" || sudo mount --bind /tmp/ask-workbench-web-next "$WEB_DIR/.next"

if [[ "${1:-}" == "--mounts-only" ]]; then
  echo "[AskAsk* Workbench] Bind mounts verified."
  exit 0
fi

if [[ ! -x "$AGENT_DIR/.venv/bin/pytest" ]] || [[ "${1:-}" == "--force-sync" ]]; then
  echo "[AskAsk* Workbench] Syncing Python dependencies via uv..."
  (
    cd "$AGENT_DIR"
    UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv sync --all-extras
    uv cache clean
  )
fi

if [[ -f "$WEB_DIR/package.json" ]] && { [[ -z "$(ls -A "$WEB_DIR/node_modules/.bin" 2>/dev/null || true)" ]] || [[ "${1:-}" == "--force-sync" ]]; }; then
  echo "[AskAsk* Workbench] Installing Next.js dependencies via npm..."
  (
    cd "$WEB_DIR"
    npm install --no-audit --no-fund
    npm cache clean --force
  )
fi

echo "[AskAsk* Workbench] Setup complete."
