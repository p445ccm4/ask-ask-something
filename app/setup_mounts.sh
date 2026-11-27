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

DEFAULT_WORKBENCH_PYPI_INDEX="${DEFAULT_WORKBENCH_PYPI_INDEX:-https://asia-east2-python.pkg.dev/gcp-prj-dat-mtb-uat-00/gcp-python-remote-repo-uat/simple}"
DEFAULT_WORKBENCH_NPM_REGISTRY="${DEFAULT_WORKBENCH_NPM_REGISTRY:-https://asia-east2-npm.pkg.dev/gcp-prj-genai-sbx/npm-sbx/}"

is_workbench_env() {
  [[ "${CLOUD_SHELL:-}" == "true" ]] && return 1
  [[ "${IS_WORKBENCH_IMAGE:-}" == "true" ]] \
    || [[ "${VERTEX_PRODUCT:-}" == "WORKBENCH_INSTANCE" ]] \
    || [[ -n "${JUPYTER_SERVER_ROOT:-}${JUPYTER_SERVER_URL:-}${JUPYTER_RUNTIME_DIR:-}${JPY_PARENT_PID:-}${DL_ANACONDA_HOME:-}" ]] \
    || [[ "${HOME:-}" == "/home/jupyter" ]] \
    || [[ -d "/opt/deeplearning" ]] \
    || [[ -f "/etc/jupyter/jupyter_server_config.py" ]] \
    || [[ -f "/etc/jupyter/jupyter_notebook_config.py" ]]
}

ensure_user_bin_path() {
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
  esac
  if [[ -d "/opt/micromamba/bin" ]] && [[ ":$PATH:" != *":/opt/micromamba/bin:"* ]]; then
    export PATH="$PATH:/opt/micromamba/bin"
  fi
}

run_pip_install() {
  local pip_cmd=()
  if command -v pip >/dev/null 2>&1; then
    pip_cmd=(pip)
  elif command -v pip3 >/dev/null 2>&1; then
    pip_cmd=(pip3)
  elif command -v python3 >/dev/null 2>&1; then
    pip_cmd=(python3 -m pip)
  else
    echo "[AskAsk* Workbench] Error: pip/python3 not found to install: $*" >&2
    return 1
  fi

  if "${pip_cmd[@]}" install --no-input "$@"; then
    return 0
  fi
  if "${pip_cmd[@]}" install --no-input --user "$@"; then
    return 0
  fi
  if "${pip_cmd[@]}" install --help 2>/dev/null | grep -Fq -- "--break-system-packages"; then
    "${pip_cmd[@]}" install --no-input --user --break-system-packages "$@"
    return $?
  fi
  return 1
}

has_gauth_keyring() {
  command -v keyring >/dev/null 2>&1 || return 1
  python3 -c "import keyring, keyrings.gauth" >/dev/null 2>&1 \
    || keyring --list-backends 2>/dev/null | grep -Fq "GooglePythonAuth"
}

pick_index_url_from_pip() {
  local raw="$1"
  local candidate=""
  local first=""
  for candidate in $raw; do
    [[ -n "$candidate" ]] || continue
    if [[ -z "$first" ]]; then
      first="$candidate"
    fi
    if [[ "$candidate" == *".pkg.dev"* ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  if [[ -n "$first" ]]; then
    printf '%s\n' "$first"
    return 0
  fi
  return 1
}

normalize_uv_index_url() {
  local url="$1"
  url="${url#"${url%%[![:space:]]*}"}"
  url="${url%"${url##*[![:space:]]}"}"
  [[ -n "$url" ]] || return 0
  if [[ "$url" == *".pkg.dev/"* ]] && [[ "$url" != */simple ]] && [[ "$url" != */simple/ ]]; then
    url="${url%/}/simple"
  fi
  printf '%s\n' "$url"
}

resolve_uv_index_url() {
  local candidate=""
  if [[ -n "${UV_DEFAULT_INDEX:-}" ]]; then
    normalize_uv_index_url "$UV_DEFAULT_INDEX"
    return 0
  fi
  if [[ -n "${UV_INDEX_URL:-}" ]]; then
    normalize_uv_index_url "$UV_INDEX_URL"
    return 0
  fi

  local pip_cmd=()
  if command -v pip >/dev/null 2>&1; then
    pip_cmd=(pip)
  elif command -v pip3 >/dev/null 2>&1; then
    pip_cmd=(pip3)
  elif command -v python3 >/dev/null 2>&1; then
    pip_cmd=(python3 -m pip)
  fi

  if (( ${#pip_cmd[@]} > 0 )); then
    local extra_urls=""
    extra_urls="$("${pip_cmd[@]}" config get global.extra-index-url 2>/dev/null || true)"
    if candidate="$(pick_index_url_from_pip "$extra_urls")"; then
      normalize_uv_index_url "$candidate"
      return 0
    fi
    local primary_urls=""
    primary_urls="$("${pip_cmd[@]}" config get global.index-url 2>/dev/null || true)"
    if candidate="$(pick_index_url_from_pip "$primary_urls")"; then
      normalize_uv_index_url "$candidate"
      return 0
    fi
  fi

  if is_workbench_env; then
    normalize_uv_index_url "$DEFAULT_WORKBENCH_PYPI_INDEX"
  fi
}

bootstrap_uv_artifact_registry() {
  ensure_user_bin_path

  local uv_config_file="${UV_CONFIG_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/uv/uv.toml}"
  local resolved_index=""
  resolved_index="$(resolve_uv_index_url || true)"

  local needs_artifact_registry=false
  if is_workbench_env || [[ "$resolved_index" == *".pkg.dev"* ]]; then
    needs_artifact_registry=true
  elif [[ -f "$uv_config_file" ]] && grep -Eq 'pkg\.dev|keyring-provider' "$uv_config_file" 2>/dev/null; then
    needs_artifact_registry=true
  fi

  local missing_pkgs=()
  if ! command -v uv >/dev/null 2>&1; then
    missing_pkgs+=(uv)
  fi
  if [[ "$needs_artifact_registry" == "true" ]] && ! has_gauth_keyring; then
    missing_pkgs+=(keyring keyrings.google-artifactregistry-auth)
  fi

  if (( ${#missing_pkgs[@]} > 0 )); then
    echo "[AskAsk* Workbench] Installing missing Python tooling: ${missing_pkgs[*]}..."
    run_pip_install "${missing_pkgs[@]}"
    ensure_user_bin_path
  fi

  if ! command -v uv >/dev/null 2>&1; then
    echo "[AskAsk* Workbench] Error: 'uv' is required but could not be found in PATH after installation." >&2
    exit 1
  fi

  if [[ "$needs_artifact_registry" == "true" ]] && [[ ! -f "$uv_config_file" ]] && [[ -n "$resolved_index" ]]; then
    echo "[AskAsk* Workbench] Configuring Artifact Registry uv index at $uv_config_file..."
    mkdir -p "$(dirname "$uv_config_file")"
    cat > "$uv_config_file" <<EOF
keyring-provider = "subprocess"

[[index]]
url = "$resolved_index"
default = true
authenticate = "always"
EOF
  fi
}

discover_workbench_npm_registry() {
  command -v gcloud >/dev/null 2>&1 || return 1
  local active_project=""
  active_project="$(gcloud config get-value project 2>/dev/null || true)"
  [[ -n "$active_project" && "$active_project" != "(unset)" ]] || return 1

  local repo_list=""
  if command -v timeout >/dev/null 2>&1; then
    repo_list="$(timeout 10 gcloud artifacts repositories list --project="$active_project" --filter="format=NPM" --format="value(name,mode)" 2>/dev/null || true)"
  else
    repo_list="$(gcloud artifacts repositories list --project="$active_project" --filter="format=NPM" --format="value(name,mode)" 2>/dev/null || true)"
  fi
  [[ -n "$repo_list" ]] || return 1

  local chosen_name=""
  local name mode
  while IFS=$'\t ' read -r name mode; do
    [[ -n "$name" ]] || continue
    if [[ -z "$chosen_name" ]]; then
      chosen_name="$name"
    fi
    if [[ "$mode" == "REMOTE_REPOSITORY" || "$mode" == "VIRTUAL_REPOSITORY" ]]; then
      chosen_name="$name"
      break
    fi
  done <<<"$repo_list"

  if [[ "$chosen_name" =~ ^projects/([^/]+)/locations/([^/]+)/repositories/([^/]+)$ ]]; then
    printf 'https://%s-npm.pkg.dev/%s/%s/\n' "${BASH_REMATCH[2]}" "${BASH_REMATCH[1]}" "${BASH_REMATCH[3]}"
    return 0
  fi
  return 1
}

resolve_npm_registry_url() {
  if [[ -n "${NPM_REGISTRY:-}" ]]; then
    printf '%s\n' "${NPM_REGISTRY%/}/"
    return 0
  fi
  if [[ -n "${NPM_CONFIG_REGISTRY:-}" ]]; then
    printf '%s\n' "${NPM_CONFIG_REGISTRY%/}/"
    return 0
  fi

  local current_registry=""
  current_registry="$(npm config get registry 2>/dev/null || true)"
  if [[ -n "$current_registry" ]] \
    && [[ "$current_registry" != "undefined" ]] \
    && [[ "$current_registry" != "null" ]] \
    && [[ "${current_registry%/}" != "https://registry.npmjs.org" ]]; then
    printf '%s\n' "${current_registry%/}/"
    return 0
  fi

  if is_workbench_env; then
    local discovered=""
    discovered="$(discover_workbench_npm_registry || true)"
    if [[ -n "$discovered" ]]; then
      printf '%s\n' "${discovered%/}/"
    else
      printf '%s\n' "${DEFAULT_WORKBENCH_NPM_REGISTRY%/}/"
    fi
    return 0
  fi

  return 0
}

configure_npm_artifact_registry() {
  local registry_url="$1"
  [[ -n "$registry_url" ]] || return 0
  [[ "$registry_url" == *".pkg.dev"* ]] || return 0

  registry_url="${registry_url%/}/"
  local registry_no_proto="${registry_url#*://}"
  local auth_prefix="//${registry_no_proto%/}/"
  local npmrc_file="${NPM_CONFIG_USERCONFIG:-$HOME/.npmrc}"

  echo "[AskAsk* Workbench] Configuring npm Artifact Registry ($registry_url)..."
  mkdir -p "$(dirname "$npmrc_file")"
  touch "$npmrc_file"
  npm config set registry "$registry_url"
  if ! grep -Fq "${auth_prefix}:always-auth=" "$npmrc_file" 2>/dev/null; then
    printf '%s:always-auth=true\n' "$auth_prefix" >> "$npmrc_file"
  fi

  local token=""
  if command -v gcloud >/dev/null 2>&1 && token="$(gcloud auth print-access-token 2>/dev/null)" && [[ -n "$token" ]]; then
    npm config set "${auth_prefix}:_authToken" "$token"
  elif command -v google-artifactregistry-auth >/dev/null 2>&1; then
    google-artifactregistry-auth
  elif command -v npx >/dev/null 2>&1; then
    npx --no-install google-artifactregistry-auth || true
  else
    echo "[AskAsk* Workbench] Warning: could not refresh Artifact Registry npm token (gcloud/google-artifactregistry-auth unavailable)." >&2
  fi
}

rewrite_lockfile_registry() {
  local lock_file="$1"
  local registry_no_trail="${2%/}"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$lock_file" "$registry_no_trail" <<'PY'
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])
target = sys.argv[2].rstrip("/")
text = lock_path.read_text(encoding="utf-8")
updated = text.replace("https://registry.npmjs.org/", f"{target}/").replace("https://registry.npmjs.org", target)
lock_path.write_text(updated, encoding="utf-8")
PY
  else
    local tmp_lock
    tmp_lock="$(mktemp)"
    sed -e "s|https://registry\.npmjs\.org/|${registry_no_trail}/|g" \
        -e "s|https://registry\.npmjs\.org|${registry_no_trail}|g" \
        "$lock_file" > "$tmp_lock"
    cat "$tmp_lock" > "$lock_file"
    rm -f "$tmp_lock"
  fi
}

bootstrap_uv_artifact_registry

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
  RESOLVED_NPM_REGISTRY="$(resolve_npm_registry_url || true)"
  if [[ -n "$RESOLVED_NPM_REGISTRY" ]]; then
    configure_npm_artifact_registry "$RESOLVED_NPM_REGISTRY"
  fi
  (
    cd "$WEB_DIR"
    lock_backup=""
    restore_package_lock() {
      if [[ -n "${lock_backup:-}" && -f "$lock_backup" ]]; then
        cat "$lock_backup" > "$WEB_DIR/package-lock.json"
        rm -f "$lock_backup"
      fi
    }
    trap restore_package_lock EXIT

    if [[ -n "$RESOLVED_NPM_REGISTRY" ]] \
      && [[ "${RESOLVED_NPM_REGISTRY%/}" != "https://registry.npmjs.org" ]] \
      && [[ -f "$WEB_DIR/package-lock.json" ]] \
      && grep -Fq "https://registry.npmjs.org" "$WEB_DIR/package-lock.json"; then
      lock_backup="$(mktemp)"
      cp -p "$WEB_DIR/package-lock.json" "$lock_backup"
      rewrite_lockfile_registry "$WEB_DIR/package-lock.json" "$RESOLVED_NPM_REGISTRY"
    fi

    if ! npm install --no-audit --no-fund; then
      echo "[AskAsk* Workbench] Error: 'npm install' failed." >&2
      echo "[AskAsk* Workbench] In VPC-SC / offline Workbench environments, verify gcloud auth / Artifact Registry permissions or override NPM_REGISTRY." >&2
      exit 1
    fi
    if [[ "$USE_TMP_MOUNTS" == "true" ]]; then
      npm cache clean --force
    fi
  )
fi

echo "[AskAsk* Workbench] Setup complete."
