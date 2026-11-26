from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from ask_workbench.deploy_service import compare_envs, execute_deploy, preview_deploy
from ask_workbench.workspaces import ProjectEntry


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

    (dev_repo / "sample-agent-service" / "src" / "prompt.py").write_text(
        'SYSTEM_PROMPT = "v2 fixed"\n', encoding="utf-8"
    )
    (dev_repo / "sample-agent-service" / "scripts" / "uat" / "results" / "uat_results.json").write_text(
        '[{"id": "Q1"}]', encoding="utf-8"
    )
    (dev_repo / "sample-agent-service" / ".ag-artifacts").mkdir(parents=True)
    (dev_repo / "sample-agent-service" / ".ag-artifacts" / "widget.html").write_text(
        "<div>ephemeral</div>", encoding="utf-8"
    )
    (dev_repo / "other-service" / "main.py").write_text("print('dirty sibling')\n", encoding="utf-8")

    proj = ProjectEntry(
        id="sample-agent",
        name="Sample Agent",
        active_env="dev",
        environments={
            "dev": str(dev_repo / "sample-agent-service"),
            "uat": str(uat_repo / "sample-agent-service"),
        },
    )

    prev = preview_deploy(proj, "dev")
    assert prev.can_deploy is True
    assert prev.mode == "direct_push"
    assert [f.path for f in prev.changed_files] == ["src/prompt.py"]
    assert "other-service" not in prev.diff
    assert ".ag-artifacts" not in prev.diff

    res = execute_deploy(proj, "dev", "fix(sample-agent-service): update prompt v2")
    assert res.ok is True
    assert res.commit_sha
    assert res.pushed_files == ["src/prompt.py"]

    sibling_status = _git(dev_repo, "status", "--porcelain", "--", "other-service")
    assert "other-service/main.py" in sibling_status

    pushed_files = _git(dev_bare, "show", "--name-only", "--pretty=format:", "main")
    assert "sample-agent-service/src/prompt.py" in pushed_files
    assert "other-service/main.py" not in pushed_files
    assert "uat_results.json" not in pushed_files
    assert ".ag-artifacts" not in pushed_files


def test_deploy_to_uat_and_prod_promotes_while_protecting_config_py(tmp_path: Path) -> None:
    sbx_repo, _ = _init_monorepo(tmp_path, "sbx_monorepo", "demo-project-sbx")
    dev_repo, dev_bare = _init_monorepo(tmp_path, "dev_monorepo", "demo-project-dev")
    uat_repo, uat_bare = _init_monorepo(tmp_path, "uat_monorepo", "demo-project-uat")
    prod_repo, prod_bare = _init_monorepo(tmp_path, "prod_monorepo", "demo-project-prod")

    # Feature branch in SBX is allowed to push directly
    _git(sbx_repo, "checkout", "-b", "feat/sbx-exp")
    (sbx_repo / "sample-agent-service" / "src" / "prompt.py").write_text(
        'SYSTEM_PROMPT = "v2 fixed"\n', encoding="utf-8"
    )
    (sbx_repo / "sample-agent-service" / "src" / "new_helper.py").write_text(
        "def helper(): return 42\n", encoding="utf-8"
    )

    proj = ProjectEntry(
        id="sample-agent",
        name="Sample Agent",
        active_env="sbx",
        environments={
            "sbx": str(sbx_repo / "sample-agent-service"),
            "dev": str(dev_repo / "sample-agent-service"),
            "uat": str(uat_repo / "sample-agent-service"),
            "prod": str(prod_repo / "sample-agent-service"),
        },
    )

    # SBX direct push works on non-main feature branch
    sbx_prev = preview_deploy(proj, "sbx")
    assert sbx_prev.can_deploy is True
    assert sbx_prev.branch == "feat/sbx-exp"

    # Promote SBX -> DEV
    dev_promo_prev = preview_deploy(proj, "dev", deploy_mode="promote", source_env="sbx")
    assert dev_promo_prev.can_deploy is True
    assert dev_promo_prev.source_env == "sbx"
    assert {f.path for f in dev_promo_prev.changed_files} == {"src/prompt.py", "src/new_helper.py"}
    assert [f.path for f in dev_promo_prev.protected_files] == ["src/config.py"]

    res_dev = execute_deploy(
        proj, "dev", "feat: promote sbx->dev", deploy_mode="promote", source_env="sbx"
    )
    assert res_dev.ok is True
    assert "v2 fixed" in _git(dev_bare, "show", "main:sample-agent-service/src/prompt.py")
    assert "demo-project-dev" in _git(dev_bare, "show", "main:sample-agent-service/src/config.py")

    # Promote DEV -> UAT
    prev_uat = preview_deploy(proj, "uat")
    assert prev_uat.can_deploy is True
    assert prev_uat.mode == "promote_from_dev"
    res_uat = execute_deploy(proj, "uat", "fix: promote v2 from dev to uat")
    assert res_uat.ok is True
    assert "v2 fixed" in _git(uat_bare, "show", "main:sample-agent-service/src/prompt.py")
    assert "demo-project-uat" in _git(uat_bare, "show", "main:sample-agent-service/src/config.py")

    # Promote UAT -> PROD
    prev_prod = preview_deploy(proj, "prod")
    assert prev_prod.can_deploy is True
    assert prev_prod.source_env == "uat"
    assert prev_prod.mode == "promote"
    res_prod = execute_deploy(proj, "prod", "release: promote uat->prod")
    assert res_prod.ok is True
    assert "v2 fixed" in _git(prod_bare, "show", "main:sample-agent-service/src/prompt.py")
    assert "demo-project-prod" in _git(prod_bare, "show", "main:sample-agent-service/src/config.py")

    cmp = compare_envs(proj, source_env="uat", target_env="prod", include_config_py=False)
    assert cmp["in_sync"] is True


def test_deploy_refuses_non_main_branch_for_dev_uat_prod(tmp_path: Path) -> None:
    dev_repo, _ = _init_monorepo(tmp_path, "dev_monorepo", "demo-project-dev")
    _git(dev_repo, "checkout", "-b", "feature/test")
    (dev_repo / "sample-agent-service" / "src" / "prompt.py").write_text("changed\n", encoding="utf-8")

    proj = ProjectEntry(
        id="sample-agent",
        name="Sample Agent",
        active_env="dev",
        environments={"dev": str(dev_repo / "sample-agent-service")},
    )
    prev = preview_deploy(proj, "dev")
    assert prev.can_deploy is False
    assert "main" in (prev.blocking_reason or "")
    with pytest.raises(ValueError, match="main"):
        execute_deploy(proj, "dev", "should fail")
