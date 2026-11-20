from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from ask_workbench.deploy_service import execute_deploy, preview_deploy
from ask_workbench.workspaces import WorkspaceEntry


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_monorepo(tmp_path: Path, name: str, env_project: str) -> tuple[Path, Path]:
    bare = tmp_path / f"{name}_origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)

    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "remote", "add", "origin", str(bare))

    svc = repo / "sample-agent-service"
    (svc / "src").mkdir(parents=True)
    (svc / "src" / "config.py").write_text(f'PROJECT_ID = "{env_project}"\n', encoding="utf-8")
    (svc / "src" / "prompt.py").write_text('SYSTEM_PROMPT = "v1"\n', encoding="utf-8")
    (svc / "scripts" / "uat" / "results").mkdir(parents=True)
    (svc / "scripts" / "uat" / "results" / "uat_results.json").write_text("[]", encoding="utf-8")

    sibling = repo / "other-service"
    sibling.mkdir(parents=True)
    (sibling / "main.py").write_text("print('other')\n", encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    _git(repo, "push", "-u", "origin", "main")
    return repo, bare


def test_deploy_to_dev_scopes_strictly_to_service_and_pushes(tmp_path: Path) -> None:
    dev_repo, dev_bare = _init_monorepo(tmp_path, "dev_monorepo", "demo-project-dev")
    uat_repo, _ = _init_monorepo(tmp_path, "uat_monorepo", "demo-project-uat")

    # Modify sample-agent-service AND sibling other-service AND transient results
    (dev_repo / "sample-agent-service" / "src" / "prompt.py").write_text(
        'SYSTEM_PROMPT = "v2 fixed"\n', encoding="utf-8"
    )
    (dev_repo / "sample-agent-service" / "scripts" / "uat" / "results" / "uat_results.json").write_text(
        '[{"id": "Q1"}]', encoding="utf-8"
    )
    (dev_repo / "other-service" / "main.py").write_text("print('dirty sibling')\n", encoding="utf-8")

    ws = WorkspaceEntry(
        id="sample-agent-dev",
        name="Sample Agent (DEV)",
        path=str(dev_repo / "sample-agent-service"),
        uat_path=str(uat_repo / "sample-agent-service"),
        env="dev",
    )

    prev = preview_deploy(ws, "dev")
    assert prev.can_deploy is True
    assert prev.mode == "direct_push"
    assert [f.path for f in prev.changed_files] == ["src/prompt.py"]
    assert "other-service" not in prev.diff

    res = execute_deploy(ws, "dev", "fix(sample-agent-service): update prompt v2")
    assert res.ok is True
    assert res.commit_sha
    assert res.pushed_files == ["src/prompt.py"]

    # Sibling dirty file must still be uncommitted in dev_repo
    sibling_status = _git(dev_repo, "status", "--porcelain", "--", "other-service")
    assert "other-service/main.py" in sibling_status

    # Bare remote received only sample-agent-service/src/prompt.py
    pushed_files = _git(dev_bare, "show", "--name-only", "--pretty=format:", "main")
    assert "sample-agent-service/src/prompt.py" in pushed_files
    assert "other-service/main.py" not in pushed_files
    assert "uat_results.json" not in pushed_files


def test_deploy_to_uat_promotes_code_while_protecting_config_py(tmp_path: Path) -> None:
    dev_repo, _ = _init_monorepo(tmp_path, "dev_monorepo", "demo-project-dev")
    uat_repo, uat_bare = _init_monorepo(tmp_path, "uat_monorepo", "demo-project-uat")

    # Update DEV prompt and add new helper module
    (dev_repo / "sample-agent-service" / "src" / "prompt.py").write_text(
        'SYSTEM_PROMPT = "v2 fixed"\n', encoding="utf-8"
    )
    (dev_repo / "sample-agent-service" / "src" / "new_helper.py").write_text(
        "def helper(): return 42\n", encoding="utf-8"
    )

    ws = WorkspaceEntry(
        id="sample-agent-dev",
        name="Sample Agent (DEV)",
        path=str(dev_repo / "sample-agent-service"),
        uat_path=str(uat_repo / "sample-agent-service"),
        env="dev",
    )

    prev = preview_deploy(ws, "uat")
    assert prev.can_deploy is True
    assert prev.mode == "promote_from_dev"
    assert {f.path for f in prev.changed_files} == {"src/prompt.py", "src/new_helper.py"}
    assert [f.path for f in prev.protected_files] == ["src/config.py"]

    res = execute_deploy(ws, "uat", "fix(sample-agent-service): promote v2 from dev to uat")
    assert res.ok is True
    assert (uat_repo / "sample-agent-service" / "src" / "prompt.py").read_text(encoding="utf-8") == (
        'SYSTEM_PROMPT = "v2 fixed"\n'
    )
    # UAT config.py must remain untouched!
    assert (uat_repo / "sample-agent-service" / "src" / "config.py").read_text(encoding="utf-8") == (
        'PROJECT_ID = "demo-project-uat"\n'
    )

    remote_prompt = _git(uat_bare, "show", "main:sample-agent-service/src/prompt.py")
    assert "v2 fixed" in remote_prompt
    remote_cfg = _git(uat_bare, "show", "main:sample-agent-service/src/config.py")
    assert "demo-project-uat" in remote_cfg


def test_deploy_refuses_non_main_branch(tmp_path: Path) -> None:
    dev_repo, _ = _init_monorepo(tmp_path, "dev_monorepo", "demo-project-dev")
    _git(dev_repo, "checkout", "-b", "feature/test")
    (dev_repo / "sample-agent-service" / "src" / "prompt.py").write_text("changed\n", encoding="utf-8")

    ws = WorkspaceEntry(
        id="sample-agent-dev",
        name="Sample Agent (DEV)",
        path=str(dev_repo / "sample-agent-service"),
        env="dev",
    )
    prev = preview_deploy(ws, "dev")
    assert prev.can_deploy is False
    assert "main" in (prev.blocking_reason or "")
    with pytest.raises(ValueError, match="main"):
        execute_deploy(ws, "dev", "should fail")
