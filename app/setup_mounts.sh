#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$APP_DIR/agent-service"
WEB_DIR="$APP_DIR/web"

ACTION="sync"
for arg in "$@"; do
  case "$arg" in
    --mounts-only)
      ACTION="mounts-only"
      ;;
    --force-sync)
      ACTION="force-sync"
      ;;
    --unmount)
      ACTION="unmount"
      ;;
    --prune)
      ACTION="prune"
      ;;
    -h|--help)
      cat <<'EOF'
Usage: setup_mounts.sh [--mounts-only | --force-sync | --unmount | --prune]

Sets up /tmp bind mounts when running on Cloud Shell or when $HOME has < 8 GB free
(override with ASK_USE_TMP_MOUNTS=true|false):
  - agent-service/.venv -> /tmp/ask-workbench-agent-venv
  - web/node_modules    -> /tmp/ask-workbench-web-node_modules
  - web/.next           -> per-checkout /tmp/ask-workbench-web-next-<path-hash>

Options:
  --mounts-only  Ensure bind mounts exist and exit without installing dependencies.
  --force-sync   Re-sync Python and Node dependencies even if already installed.
  --unmount      Unmount this checkout's bind mounts and remove its .next cache in /tmp.
  --prune        Unmount this checkout and delete unmounted /tmp/ask-workbench-* directories.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Run '$(basename "$0") --help' for usage." >&2
      exit 1
      ;;
  esac
done

WORKTREE_ID="$(printf '%s' "$APP_DIR" | sha256sum | cut -c1-12)"
TMP_VENV_DIR="/tmp/ask-workbench-agent-venv"
TMP_NODE_MODULES_DIR="/tmp/ask-workbench-web-node_modules"
TMP_NEXT_DIR="/tmp/ask-workbench-web-next-${WORKTREE_ID}"

unmount_checkout_mounts() {
  for dst in "$AGENT_DIR/.venv" "$WEB_DIR/node_modules" "$WEB_DIR/.next"; do
    if mountpoint -q "$dst" 2>/dev/null; then
      sudo umount "$dst"
    fi
  done
  rm -rf "$TMP_NEXT_DIR"
}

if [[ "$ACTION" == "unmount" ]]; then
  unmount_checkout_mounts
  echo "[AskAsk* Workbench] Unmounted checkout bind mounts and cleared $TMP_NEXT_DIR."
  exit 0
fi

if [[ "$ACTION" == "prune" ]]; then
  unmount_checkout_mounts
  active_sources="$(findmnt -rn -o SOURCE 2>/dev/null || true)"
  for dir in /tmp/ask-workbench-*; do
    [[ -e "$dir" ]] || continue
    if grep -Fq "$dir" <<<"$active_sources"; then
      echo "[AskAsk* Workbench] Keeping active mount target: $dir"
    else
      rm -rf "$dir"
      echo "[AskAsk* Workbench] Removed unmounted /tmp directory: $dir"
    fi
  done
  exit 0
fi

APP_FS_TYPE="$(df -PT "$APP_DIR" 2>/dev/null | awk 'NR==2 {print $2}' || true)"
if [[ "$APP_FS_TYPE" == *fuse* || "$APP_FS_TYPE" == *gcs* ]]; then
  echo "[AskAsk* Workbench] Warning: $APP_DIR is on filesystem '$APP_FS_TYPE' (FUSE/GCSFuse)." >&2
  echo "[AskAsk* Workbench] SQLite (.data/*.db) and symlinks (.venv, node_modules) may fail on GCSFuse." >&2
fi

should_use_tmp_mounts() {
  case "${ASK_USE_TMP_MOUNTS:-}" in
    true|1|yes) return 0 ;;
    false|0|no) return 1 ;;
  esac

  if [[ "${CLOUD_SHELL:-}" == "true" ]]; then
    return 0
  fi

  local home_avail_kb
  home_avail_kb="$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
  if [[ "$home_avail_kb" =~ ^[0-9]+$ ]] && (( home_avail_kb < 8388608 )); then
    return 0
  fi

  return 1
}

USE_TMP_MOUNTS=false
if should_use_tmp_mounts; then
  USE_TMP_MOUNTS=true
fi

ensure_tmp_bind_mount() {
  local src="$1"
  local dst="$2"
  mkdir -p "$src"
  if [[ -L "$dst" ]]; then
    rm -f "$dst"
  fi
  mkdir -p "$dst"
  if mountpoint -q "$dst"; then
    local current_src
    current_src="$(findmnt -rn -o SOURCE "$dst" 2>/dev/null || true)"
    case "$current_src" in
      *"[${src}]"|"$src")
        return 0
        ;;
      *)
        sudo umount "$dst"
        ;;
    esac
  fi
  sudo mount --bind "$src" "$dst"
}

if [[ "$USE_TMP_MOUNTS" == "true" ]]; then
  echo "[AskAsk* Workbench] Ensuring /tmp bind mounts for low-disk compliance..."

  mkdir -p /tmp/xdg-cache /tmp/npm-cache /tmp/uv-python "$HOME/.cache" "$HOME/.npm"
  chmod 700 /tmp/xdg-cache "$HOME/.cache"
  mountpoint -q "$HOME/.cache" || sudo mount --bind /tmp/xdg-cache "$HOME/.cache"
  mountpoint -q "$HOME/.npm" || sudo mount --bind /tmp/npm-cache "$HOME/.npm"

  ensure_tmp_bind_mount "$TMP_VENV_DIR" "$AGENT_DIR/.venv"
  ensure_tmp_bind_mount "$TMP_NODE_MODULES_DIR" "$WEB_DIR/node_modules"
  ensure_tmp_bind_mount "$TMP_NEXT_DIR" "$WEB_DIR/.next"
else
  echo "[AskAsk* Workbench] Sufficient local disk detected; skipping /tmp bind mounts."
fi

if [[ "$ACTION" == "mounts-only" ]]; then
  echo "[AskAsk* Workbench] Bind mounts verified."
  exit 0
fi

if [[ ! -x "$AGENT_DIR/.venv/bin/pytest" ]] || [[ "$ACTION" == "force-sync" ]]; then
  echo "[AskAsk* Workbench] Syncing Python dependencies via uv..."
  (
    cd "$AGENT_DIR"
    if [[ "$USE_TMP_MOUNTS" == "true" ]]; then
      UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/tmp/uv-python}" uv sync --all-extras --no-install-project
      rm -f "$AGENT_DIR"/.venv/lib/python*/site-packages/*ag_workbench*.pth \
            "$AGENT_DIR"/.venv/lib/python*/site-packages/*ask_workbench*.pth
      UV_LOCK_TIMEOUT=3 uv cache clean || true
    else
      UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/tmp/uv-python}" uv sync --all-extras
    fi
  )
fi

if [[ -f "$WEB_DIR/package.json" ]] && { [[ -z "$(ls -A "$WEB_DIR/node_modules/.bin" 2>/dev/null || true)" ]] || [[ "$ACTION" == "force-sync" ]]; }; then
  echo "[AskAsk* Workbench] Installing Next.js dependencies via npm..."
  (
    cd "$WEB_DIR"
    npm install --no-audit --no-fund
    if [[ "$USE_TMP_MOUNTS" == "true" ]]; then
      npm cache clean --force
    fi
  )
fi

echo "[AskAsk* Workbench] Setup complete."
