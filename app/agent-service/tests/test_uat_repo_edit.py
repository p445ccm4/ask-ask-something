from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.antigravity.hooks import hooks, policy
from google.antigravity.types import ToolCall

from ag_workbench.approval_broker import ApprovalBroker
from ask_workbench.agent_runner import (
    build_host_tools,
    build_policies,
    build_system_instructions,
    build_workbench_hooks,
)
from ask_workbench.ask_workbench_db import AskWorkbenchDB
from ask_workbench.config import Settings
from ask_workbench.deploy_service import execute_deploy, preview_deploy
from ask_workbench.main import create_app
from ask_workbench.uat_service import EvalService
from ask_workbench.workspaces import ProjectEntry, ProjectRegistry


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _create_paired_repos(
    tmp_path: Path,
    *,
    with_remotes: bool = False,
) -> tuple[Path, Path, ProjectEntry, Path | None, Path | None]:
    dev_repo = tmp_path / "dev-svc"
    uat_repo = tmp_path / "uat-svc"
    dev_bare: Path | None = None
    uat_bare: Path | None = None

    for repo, env_label, score_status in (
        (dev_repo, "dev", "PASS"),
        (uat_repo, "uat", "FAIL"),
    ):
        bare: Path | None = None
        if with_remotes:
            bare = tmp_path / f"{env_label}_origin.git"
            subprocess.run(
                ["git", "init", "--bare", "-b", "main", str(bare)],
                check=True,
                capture_output=True,
            )
            if env_label == "dev":
                dev_bare = bare
            else:
                uat_bare = bare

        (repo / "src").mkdir(parents=True)
        (repo / "scripts" / "uat" / "results").mkdir(parents=True)
        (repo / "src" / "config.py").write_text(
            f'PROJECT_ID = "proj-{env_label}"\n', encoding="utf-8"
        )
        (repo / "src" / "prompt.py").write_text(
            'SYSTEM_PROMPT = "shared-v1"\n' if with_remotes else f'LINE1 = "{env_label}"\nLINE2 = "hello"\n',
            encoding="utf-8",
        )
        (repo / ".env").write_text("SECRET_TOKEN=supersecret\n", encoding="utf-8")
        (repo / ".env.example").write_text("SECRET_TOKEN=\n", encoding="utf-8")
        (repo / "private.key").write_text("PRIVATE KEY", encoding="utf-8")
        (repo / "scripts" / "uat" / "uat_config.json").write_text(
            json.dumps({"agent_name": f"Agent-{env_label}", "endpoint": f"https://{env_label}.run.app"}),
            encoding="utf-8",
        )
        (repo / "scripts" / "uat" / "uat_questions.json").write_text(
            json.dumps([{"id": "Q1", "turns": [{"question": "Hi", "expected_answer": "Hello"}]}]),
            encoding="utf-8",
        )
        (repo / "scripts" / "uat" / "results" / "uat_results.json").write_text(
            json.dumps(
                [
                    {
                        "id": "Q1",
                        "uat_review": {
                            "status": score_status,
                            "score": 1.0 if score_status == "PASS" else 0.0,
                            "comment": f"reviewed-{env_label}",
                        },
                        "turns": [
                            {
                                "turn": 1,
                                "question": "Hi",
                                "raw_response": {"text": f"Resp-{env_label}", "sources": []},
                                "uat_review": {
                                    "status": score_status,
                                    "score": 1.0 if score_status == "PASS" else 0.0,
                                    "comment": f"reviewed-{env_label}",
                                },
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test User")
        if bare is not None:
            _git(repo, "remote", "add", "origin", str(bare))
        (repo / ".gitignore").write_text(
            ".env\nprivate.key\nescape_link.txt\nenv_link.txt\n",
            encoding="utf-8",
        )
        _git(repo, "add", ".gitignore", "src", ".env.example", "scripts/uat/uat_config.json", "scripts/uat/uat_questions.json")
        _git(repo, "commit", "-m", f"init {env_label}")
        if bare is not None:
            _git(repo, "push", "-u", "origin", "main")

    outside_file = tmp_path / "outside-secret.txt"
    outside_file.write_text("OUTSIDE", encoding="utf-8")
    (uat_repo / "escape_link.txt").symlink_to(outside_file)
    (uat_repo / "env_link.txt").symlink_to(uat_repo / ".env")

    proj = ProjectEntry(
        id="sample-ws",
        name="Sample Agent",
        active_env="dev",
        environments={"dev": str(dev_repo), "uat": str(uat_repo)},
    )
    return dev_repo, uat_repo, proj, dev_bare, uat_bare


def test_hooks_wire_multi_env_paths_instructions_and_git_updates(tmp_path: Path) -> None:
    dev_repo, uat_repo, _, _, _ = _create_paired_repos(tmp_path)
    (dev_repo / "src" / "dev_dirty.py").write_text("DEV = 1\n", encoding="utf-8")
    (uat_repo / "src" / "uat_dirty.py").write_text("UAT = 1\n", encoding="utf-8")

    proj_single = ProjectEntry(id="no-uat", name="No UAT", active_env="dev", environments={"dev": str(dev_repo)})
    inst_single = build_system_instructions(proj_single, "read_only")
    assert "MULTI-ENVIRONMENT PROJECT WORKSPACE" not in inst_single
    assert ".ag-artifacts/" in inst_single

    db = AskWorkbenchDB(tmp_path / "wb.db")
    reg = ProjectRegistry(db, seed_defaults=False)
    entry = reg.add_project(
        name="Sample Agent",
        environments={"dev": str(dev_repo), "uat": str(uat_repo)},
    )
    summary = reg.summarize(entry)
    assert summary.env_git["uat"].branch == "main"
    assert summary.env_git["uat"].dirty_count == 1
    assert summary.dirty_count == 1

    inst_multi = build_system_instructions(entry, "sandboxed_auto")
    assert "MULTI-ENVIRONMENT PROJECT WORKSPACE" in inst_multi
    assert str(uat_repo.resolve()) in inst_multi
    assert "compare_envs" in inst_multi

    workbench_hooks = build_workbench_hooks(reg, EvalService(db))
    ws_ctx = workbench_hooks.resolve_workspace(entry.id)
    assert ws_ctx.path == str(dev_repo.resolve())
    assert ws_ctx.extra_paths == [str(uat_repo.resolve())]

    # Switching active_env to uat flips primary workspace path while keeping project workspace ID!
    reg.update_project(entry.id, active_env="uat")
    ws_ctx_uat = workbench_hooks.resolve_workspace(entry.id)
    assert ws_ctx_uat.id == entry.id
    assert ws_ctx_uat.path == str(uat_repo.resolve())
    assert ws_ctx_uat.extra_paths == [str(dev_repo.resolve())]

    assert workbench_hooks.on_turn_mutated is not None
    mutated_ev = workbench_hooks.on_turn_mutated(ws_ctx_uat)
    assert mutated_ev["type"] == "git_diff_updated"
    assert any(f["path"] == "src/uat_dirty.py" for f in mutated_ev["git"]["changed_files"])
    assert any(f["path"] == "src/dev_dirty.py" for f in mutated_ev["env_git"]["dev"]["changed_files"])


async def test_ask_host_tools_compare_and_sqlite_eval_queries(tmp_path: Path) -> None:
    dev_repo, uat_repo, _, _, _ = _create_paired_repos(tmp_path)
    (dev_repo / "src" / "dev_only.py").write_text("DEV_ONLY = True\n", encoding="utf-8")
    (uat_repo / "src" / "uat_only.py").write_text("UAT_ONLY = True\n", encoding="utf-8")

    db = AskWorkbenchDB(tmp_path / "wb.db")
    reg = ProjectRegistry(db, seed_defaults=False)
    proj = reg.add_project(
        name="Sample Agent",
        environments={"dev": str(dev_repo), "uat": str(uat_repo)},
    )
    eval_svc = EvalService(db, templates_dir=tmp_path / "tmpl", exports_dir=tmp_path / "exp")

    expected_read_tools = {
        "list_eval_suites",
        "get_eval_summary",
        "query_eval_cases",
        "get_eval_case_detail",
        "get_git_diff",
        "compare_envs",
    }

    for mode in ("read_only", "ask_before_fix", "sandboxed_auto", "unsandboxed_auto"):
        tools = {fn.__name__: fn for fn in build_host_tools(proj, eval_svc, mode, registry=reg)}  # type: ignore[arg-type]
        assert expected_read_tools.issubset(tools.keys())
        assert "execute_deploy" not in tools
        assert "preview_deploy" not in tools

    broker = ApprovalBroker()

    async def emit(_: dict) -> None:
        return None

    for mode in ("read_only", "ask_before_fix"):
        policies = build_policies(mode, f"conv-{mode}", broker, emit)  # type: ignore[arg-type]
        hook = policy.enforce(policies)
        for name in expected_read_tools:
            res = await hook.run(hooks.HookContext(), ToolCall(name=name, args={}))
            assert res.allow is True, f"{name} should be auto-allowed in {mode}"
            assert broker.list_pending() == []

    tools = {fn.__name__: fn for fn in build_host_tools(proj, eval_svc, "read_only", registry=reg)}

    cmp_res = await tools["compare_envs"](source_env="dev", target_env="uat", include_config_py=False)
    assert cmp_res["in_sync"] is False
    assert "src/dev_only.py" in {f["path"] for f in cmp_res["changed_files"]}
    assert [f["path"] for f in cmp_res["protected_files"]] == ["src/config.py"]
    assert "src/uat_only.py" in cmp_res["uat_only_files"]

    dev_sum = await tools["get_eval_summary"](env="dev")
    uat_sum = await tools["get_eval_summary"](env="uat")
    assert dev_sum["summary"]["pass_count"] == 1
    assert uat_sum["summary"]["fail_count"] == 1
    assert uat_sum["env"] == "uat"

    dev_case = await tools["get_eval_case_detail"]("Q1", env="dev")
    uat_case = await tools["get_eval_case_detail"]("Q1", env="uat")
    assert dev_case["case"]["eval_review"]["comment"] == "reviewed-dev"
    assert uat_case["case"]["eval_review"]["comment"] == "reviewed-uat"

    dev_git = await tools["get_git_diff"](env="dev")
    uat_git = await tools["get_git_diff"](env="uat")
    assert dev_git["git_toplevel"] == str(dev_repo.resolve())
    assert uat_git["git_toplevel"] == str(uat_repo.resolve())
    assert any(f["path"] == "src/dev_only.py" for f in dev_git["changed_files"])
    assert any(f["path"] == "src/uat_only.py" for f in uat_git["changed_files"])

    # Mutating host tool writes to SQLite only, never touches target repo
    edit_tools = {fn.__name__: fn for fn in build_host_tools(proj, eval_svc, "sandboxed_auto", registry=reg)}
    created = await edit_tools["create_or_update_eval_suite"](
        name="Smoke Suite", env="dev", config={"endpoint": "https://smoke.run.app/chat"}
    )
    assert created["ok"] is True
    sid = created["suite"]["id"]
    upserted = await edit_tools["upsert_eval_cases"](
        suite_id=sid,
        env="dev",
        cases=[{"id": "S1", "turns": [{"question": "Smoke?", "expected_answer": "Yes"}]}],
    )
    assert upserted["ok"] is True
    assert upserted["upserted_count"] == 1
    suites_res = await tools["list_eval_suites"](env="dev")
    assert suites_res["total"] == 2


def test_api_file_endpoint_git_diff_and_eval_overview_with_env_param(tmp_path: Path) -> None:
    dev_repo, uat_repo, _, _, _ = _create_paired_repos(tmp_path)
    (uat_repo / "src" / "uat_only.py").write_text("UAT_ONLY = True\n", encoding="utf-8")

    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    client = TestClient(app)

    add_resp = client.post(
        "/projects",
        json={"name": "Paired Project", "environments": {"dev": str(dev_repo), "uat": str(uat_repo)}},
    )
    assert add_resp.status_code == 200
    pid = add_resp.json()["project"]["id"]

    r_dev = client.get(f"/workspaces/{pid}/file", params={"path": "src/prompt.py", "format": "json"})
    assert r_dev.status_code == 200
    assert 'LINE1 = "dev"' in r_dev.json()["content"]

    r_uat_abs = client.get(
        f"/workspaces/{pid}/file",
        params={"path": str(uat_repo / "src" / "prompt.py"), "format": "json"},
    )
    assert r_uat_abs.status_code == 200
    assert 'LINE1 = "uat"' in r_uat_abs.json()["content"]

    r_uat_rel = client.get(
        f"/workspaces/{pid}/file",
        params={"path": "src/uat_only.py", "format": "json"},
    )
    assert r_uat_rel.status_code == 200
    assert "UAT_ONLY = True" in r_uat_rel.json()["content"]

    for forbidden in (
        str(uat_repo / ".env"),
        str(uat_repo / "private.key"),
        str(uat_repo / "escape_link.txt"),
        str(uat_repo / "env_link.txt"),
        str(uat_repo / ".git" / "HEAD"),
        str(tmp_path / "outside-secret.txt"),
    ):
        assert client.get(f"/workspaces/{pid}/file", params={"path": forbidden}).status_code == 403

    assert client.get(f"/workspaces/{pid}/file", params={"path": "src/missing.py"}).status_code == 404

    gd_uat = client.get(f"/projects/{pid}/git-diff", params={"env": "uat"})
    assert gd_uat.status_code == 200
    assert any(f["path"] == "src/uat_only.py" for f in gd_uat.json()["changed_files"])

    ov_dev = client.get(f"/projects/{pid}/eval/overview", params={"env": "dev"})
    ov_uat = client.get(f"/projects/{pid}/eval/overview", params={"env": "uat"})
    assert ov_dev.status_code == 200 and ov_dev.json()["summary"]["pass_count"] == 1
    assert ov_uat.status_code == 200 and ov_uat.json()["summary"]["fail_count"] == 1
    assert ov_uat.json()["env"] == "uat"


def test_deploy_direct_uat_push_and_overlap_conflict_guard(tmp_path: Path) -> None:
    dev_repo, uat_repo, proj, _, uat_bare = _create_paired_repos(tmp_path, with_remotes=True)
    assert uat_bare is not None

    (uat_repo / "src" / "prompt.py").write_text('SYSTEM_PROMPT = "uat-hotfix"\n', encoding="utf-8")
    prev_direct = preview_deploy(proj, "uat", deploy_mode="auto")
    assert prev_direct.mode == "direct_push"
    assert prev_direct.can_deploy is True
    assert prev_direct.has_direct_uat_changes is True
    assert prev_direct.direct_uat_files == ["src/prompt.py"]
    assert [f.path for f in prev_direct.changed_files] == ["src/prompt.py"]

    res_direct = execute_deploy(proj, "uat", "fix: hotfix prompt directly in uat")
    assert res_direct.ok is True
    assert "uat-hotfix" in _git(uat_bare, "show", "main:src/prompt.py")

    (dev_repo / "src" / "prompt.py").write_text('SYSTEM_PROMPT = "dev-v2"\n', encoding="utf-8")
    (uat_repo / "src" / "prompt.py").write_text('SYSTEM_PROMPT = "uat-uncommitted"\n', encoding="utf-8")
    (uat_repo / "src" / "uat_local.py").write_text("KEEP_LOCAL = True\n", encoding="utf-8")

    prev_conflict = preview_deploy(proj, "uat", deploy_mode="promote_from_dev", force_overwrite_uat=False)
    assert prev_conflict.mode == "promote_from_dev"
    assert prev_conflict.can_deploy is False
    assert prev_conflict.overlap_conflict_files == ["src/prompt.py"]
    assert "overlap" in (prev_conflict.blocking_reason or "").lower()

    with pytest.raises(ValueError, match="overlap"):
        execute_deploy(proj, "uat", "should fail", deploy_mode="promote_from_dev", force_overwrite_uat=False)

    prev_forced = preview_deploy(proj, "uat", deploy_mode="promote_from_dev", force_overwrite_uat=True)
    assert prev_forced.can_deploy is True
    res_forced = execute_deploy(
        proj,
        "uat",
        "fix: promote dev-v2 over direct uat edit",
        deploy_mode="promote_from_dev",
        force_overwrite_uat=True,
    )
    assert res_forced.ok is True
    assert res_forced.pushed_files == ["src/prompt.py"]
    assert "dev-v2" in _git(uat_bare, "show", "main:src/prompt.py")
    assert "src/uat_local.py" in _git(uat_repo, "status", "--porcelain")
