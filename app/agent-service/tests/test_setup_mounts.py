from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[2]
SETUP_MOUNTS = APP_DIR / "setup_mounts.sh"


def _write_exe(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _prepare_fixture(
    tmp_path: Path,
    *,
    with_uv: bool = False,
    with_keyring: bool = False,
    pip_extra_index: str = "",
    pip_index: str = "",
    gcloud_repo_output: str = "",
    npm_install_exit: int = 0,
) -> tuple[Path, Path, Path, Path]:
    ws = tmp_path / "app"
    (ws / "agent-service").mkdir(parents=True)
    (ws / "web").mkdir(parents=True)
    (ws / "vendor" / "antigravity-workbench" / "scripts").mkdir(parents=True)
    shutil.copy2(SETUP_MOUNTS, ws / "setup_mounts.sh")
    shutil.copy2(
        APP_DIR / "vendor" / "antigravity-workbench" / "scripts" / "artifact_registry.sh",
        ws / "vendor" / "antigravity-workbench" / "scripts" / "artifact_registry.sh",
    )

    (ws / "web" / "package.json").write_text('{"name": "ask-workbench-web"}\n', encoding="utf-8")
    (ws / "web" / "package-lock.json").write_text(
        '{\n  "packages": {\n    "node_modules/foo": {\n      "resolved": "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz"\n    }\n  }\n}\n',
        encoding="utf-8",
    )

    home = tmp_path / "home"
    home.mkdir()
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    if with_uv:
        _write_exe(
            fake_bin / "uv",
            f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{logs_dir}/uv.log"
""",
        )

    if with_keyring:
        pkg_dir = site_dir / "keyrings"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        (pkg_dir / "gauth.py").write_text("class GooglePythonAuth: pass\n", encoding="utf-8")
        _write_exe(
            fake_bin / "keyring",
            """#!/usr/bin/env bash
if [[ "${1:-}" == "--list-backends" ]]; then
  echo "keyrings.gauth.GooglePythonAuth"
fi
""",
        )

    _write_exe(
        fake_bin / "pip",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "config" && "${{2:-}}" == "get" ]]; then
  case "${{3:-}}" in
    global.extra-index-url)
      if [[ -n "{pip_extra_index}" ]]; then
        printf '%s\\n' "{pip_extra_index}"
        exit 0
      fi
      exit 1
      ;;
    global.index-url)
      if [[ -n "{pip_index}" ]]; then
        printf '%s\\n' "{pip_index}"
        exit 0
      fi
      exit 1
      ;;
  esac
  exit 1
fi
if [[ "${{1:-}}" == "install" ]]; then
  if [[ "${{2:-}}" == "--help" ]]; then
    echo "--break-system-packages"
    exit 0
  fi
  printf '%s\\n' "$*" >> "{logs_dir}/pip_install.log"
  mkdir -p "$HOME/.local/bin"
  for arg in "$@"; do
    case "$arg" in
      uv)
        cat > "$HOME/.local/bin/uv" <<'UVEOF'
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{logs_dir}/uv.log"
UVEOF
        chmod +x "$HOME/.local/bin/uv"
        ;;
      keyring)
        mkdir -p "{site_dir}/keyring"
        printf '' > "{site_dir}/keyring/__init__.py"
        cat > "$HOME/.local/bin/keyring" <<'KREOF'
#!/usr/bin/env bash
if [[ "${{1:-}}" == "--list-backends" ]]; then
  echo "keyrings.gauth.GooglePythonAuth"
fi
KREOF
        chmod +x "$HOME/.local/bin/keyring"
        ;;
      keyrings.google-artifactregistry-auth)
        mkdir -p "{site_dir}/keyrings"
        touch "{site_dir}/keyrings/__init__.py"
        printf 'class GooglePythonAuth: pass\\n' > "{site_dir}/keyrings/gauth.py"
        ;;
    esac
  done
  exit 0
fi
exit 1
""",
    )

    _write_exe(
        fake_bin / "gcloud",
        f"""#!/usr/bin/env bash
case "$*" in
  "config get-value project"*)
    echo "gcp-prj-genai-sbx"
    exit 0
    ;;
  "artifacts repositories list"*)
    printf '%b' "{gcloud_repo_output}"
    exit 0
    ;;
  "auth print-access-token"*)
    echo "ya29.mock-token-123"
    exit 0
    ;;
esac
exit 1
""",
    )

    _write_exe(
        fake_bin / "npm",
        f"""#!/usr/bin/env bash
set -euo pipefail
npmrc="${{NPM_CONFIG_USERCONFIG:-$HOME/.npmrc}}"
if [[ "${{1:-}}" == "config" && "${{2:-}}" == "get" && "${{3:-}}" == "registry" ]]; then
  if [[ -f "$npmrc" ]] && grep -q '^registry=' "$npmrc"; then
    grep '^registry=' "$npmrc" | tail -n 1 | cut -d= -f2-
  else
    echo "https://registry.npmjs.org/"
  fi
  exit 0
fi
if [[ "${{1:-}}" == "config" && "${{2:-}}" == "set" ]]; then
  key="$3"
  val="$4"
  touch "$npmrc"
  grep -vF "${{key}}=" "$npmrc" > "${{npmrc}}.tmp" || true
  printf '%s=%s\\n' "$key" "$val" >> "${{npmrc}}.tmp"
  mv "${{npmrc}}.tmp" "$npmrc"
  exit 0
fi
if [[ "${{1:-}}" == "install" ]]; then
  cp package-lock.json "{logs_dir}/lock_seen_by_npm.json"
  exit {npm_install_exit}
fi
exit 0
""",
    )

    return ws, home, fake_bin, logs_dir


def _build_env(home: Path, fake_bin: Path, site_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    python_dir = str(Path(os.sys.executable).parent)
    env = {
        "HOME": str(home),
        "PATH": f"{fake_bin}:{python_dir}:/usr/bin:/bin",
        "PYTHONPATH": str(site_dir),
        "ASK_USE_TMP_MOUNTS": "false",
    }
    if extra:
        env.update(extra)
    return env


def test_workbench_bootstraps_uv_and_npm_artifact_registry(tmp_path: Path) -> None:
    ws, home, fake_bin, logs_dir = _prepare_fixture(
        tmp_path,
        with_uv=False,
        with_keyring=False,
        pip_extra_index="https://asia-east2-python.pkg.dev/gcp-prj-dat-mtb-uat-00/gcp-python-remote-repo-uat/simple",
        gcloud_repo_output="projects/gcp-prj-genai-sbx/locations/asia-east2/repositories/npm-sbx\\tREMOTE_REPOSITORY\\n",
    )
    env = _build_env(
        home,
        fake_bin,
        tmp_path / "site",
        {"IS_WORKBENCH_IMAGE": "true", "VERTEX_PRODUCT": "WORKBENCH_INSTANCE"},
    )

    res = subprocess.run([str(ws / "setup_mounts.sh")], env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    pip_log = (logs_dir / "pip_install.log").read_text(encoding="utf-8")
    assert "uv" in pip_log
    assert "keyrings.google-artifactregistry-auth" in pip_log

    uv_toml = (home / ".config" / "uv" / "uv.toml").read_text(encoding="utf-8")
    assert 'keyring-provider = "subprocess"' in uv_toml
    assert "https://asia-east2-python.pkg.dev/gcp-prj-dat-mtb-uat-00/gcp-python-remote-repo-uat/simple" in uv_toml
    assert 'authenticate = "always"' in uv_toml

    npmrc = (home / ".npmrc").read_text(encoding="utf-8")
    assert "registry=https://asia-east2-npm.pkg.dev/gcp-prj-genai-sbx/npm-sbx/" in npmrc
    assert "//asia-east2-npm.pkg.dev/gcp-prj-genai-sbx/npm-sbx/:always-auth=true" in npmrc
    assert "//asia-east2-npm.pkg.dev/gcp-prj-genai-sbx/npm-sbx/:_authToken=ya29.mock-token-123" in npmrc

    lock_seen = (logs_dir / "lock_seen_by_npm.json").read_text(encoding="utf-8")
    assert "https://asia-east2-npm.pkg.dev/gcp-prj-genai-sbx/npm-sbx/foo/-/foo-1.0.0.tgz" in lock_seen
    assert "registry.npmjs.org" not in lock_seen

    lock_after = (ws / "web" / "package-lock.json").read_text(encoding="utf-8")
    assert "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz" in lock_after


def test_workbench_restores_package_lock_on_npm_install_failure(tmp_path: Path) -> None:
    ws, home, fake_bin, _logs_dir = _prepare_fixture(
        tmp_path,
        with_uv=True,
        with_keyring=True,
        npm_install_exit=1,
    )
    original_lock = (ws / "web" / "package-lock.json").read_text(encoding="utf-8")
    env = _build_env(home, fake_bin, tmp_path / "site", {"VERTEX_PRODUCT": "WORKBENCH_INSTANCE"})

    res = subprocess.run([str(ws / "setup_mounts.sh")], env=env, capture_output=True, text=True)
    assert res.returncode != 0
    assert (ws / "web" / "package-lock.json").read_text(encoding="utf-8") == original_lock


def test_non_workbench_cloud_shell_skips_artifact_registry(tmp_path: Path) -> None:
    ws, home, fake_bin, logs_dir = _prepare_fixture(
        tmp_path,
        with_uv=True,
        with_keyring=False,
    )
    env = _build_env(home, fake_bin, tmp_path / "site", {"CLOUD_SHELL": "true"})

    res = subprocess.run([str(ws / "setup_mounts.sh")], env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    assert not (logs_dir / "pip_install.log").exists()
    assert not (home / ".config" / "uv" / "uv.toml").exists()
    assert not (home / ".npmrc").exists()
    lock_seen = (logs_dir / "lock_seen_by_npm.json").read_text(encoding="utf-8")
    assert "https://registry.npmjs.org/foo/-/foo-1.0.0.tgz" in lock_seen
