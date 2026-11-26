from __future__ import annotations

import json
from pathlib import Path
import pytest

from ask_workbench.ask_workbench_db import AskWorkbenchDB
from ask_workbench.uat_service import EvalService
from ask_workbench.workspaces import ProjectRegistry


def test_project_registry_crud_and_validation(tmp_path: Path) -> None:
    sbx = tmp_path / "demo-sbx"
    dev = tmp_path / "demo-dev"
    uat = tmp_path / "demo-uat"
    prod = tmp_path / "demo-prod"
    for d in (sbx, dev, uat, prod):
        d.mkdir()

    db = AskWorkbenchDB(tmp_path / "wb.db")
    reg = ProjectRegistry(db, seed_defaults=False)
    assert reg.list_entries() == []

    with pytest.raises(ValueError, match="At least one environment"):
        reg.add_project(name="Empty", environments={})

    proj = reg.add_project(
        name="Demo Agent",
        environments={"sbx": str(sbx), "dev": str(dev)},
    )
    assert proj.active_env == "dev"
    assert proj.configured_envs == ["sbx", "dev"]

    updated = reg.update_project(
        proj.id,
        environments={"sbx": str(sbx), "dev": str(dev), "uat": str(uat), "prod": str(prod)},
        active_env="uat",
    )
    assert updated.active_env == "uat"
    assert updated.path == str(uat.resolve())
    assert updated.configured_envs == ["sbx", "dev", "uat", "prod"]

    summaries = reg.list_summaries()
    assert len(summaries) == 1
    assert set(summaries[0].env_git.keys()) == {"sbx", "dev", "uat", "prod"}
    assert reg.delete_project(proj.id) is True
    assert reg.list_entries() == []


def test_project_registry_migrates_legacy_workspaces_json(tmp_path: Path) -> None:
    dev = tmp_path / "seeded-dev"
    uat = tmp_path / "seeded-uat"
    dev.mkdir()
    uat.mkdir()

    legacy_file = tmp_path / "workspaces.json"
    legacy_file.write_text(
        json.dumps(
            [
                {
                    "id": "askhr",
                    "name": "AskHR",
                    "path": str(dev),
                    "uat_path": str(uat),
                    "env": "dev",
                }
            ]
        ),
        encoding="utf-8",
    )

    db = AskWorkbenchDB(tmp_path / "wb.db")
    reg = ProjectRegistry(db, legacy_registry_file=legacy_file, seed_defaults=False)
    entries = reg.list_entries()
    assert len(entries) == 1
    assert entries[0].id == "askhr"
    assert entries[0].environments == {
        "dev": str(dev.resolve()),
        "uat": str(uat.resolve()),
    }


def test_read_only_legacy_import_into_sqlite_without_target_repo_writes(tmp_path: Path) -> None:
    repo = tmp_path / "legacy-agent"
    dev_dir = repo / "scripts" / "dev"
    dev_dir.mkdir(parents=True)
    (dev_dir / "uat_config.json").write_text(
        json.dumps({"agent_name": "Legacy Bot", "endpoint": "https://legacy.run.app/chat"}),
        encoding="utf-8",
    )
    (dev_dir / "uat_questions_full.json").write_text(
        json.dumps([{"id": "Q1", "turns": [{"question": "Hi", "expected_answer": "Hello"}]}]),
        encoding="utf-8",
    )
    (dev_dir / "uat_results.json").write_text(
        json.dumps(
            [
                {
                    "id": "Q1",
                    "uat_review": {"status": "PARTIAL", "score": 0.5, "comment": "Partial match"},
                    "turns": [
                        {
                            "turn": 1,
                            "question": "Hi",
                            "raw_response": {"text": "Hey", "sources": ["doc.pdf"]},
                            "uat_review": {"status": "PARTIAL", "score": 0.5},
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    before_files = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())

    db = AskWorkbenchDB(tmp_path / "wb.db")
    reg = ProjectRegistry(db, seed_defaults=False)
    proj = reg.add_project(name="Legacy Agent", environments={"dev": str(repo)})
    svc = EvalService(db, templates_dir=tmp_path / "templates", exports_dir=tmp_path / "exports")

    overview = svc.get_overview(proj, env="dev")
    assert overview["has_config"] is True
    assert overview["has_questions"] is True
    assert overview["has_results"] is True
    assert overview["questions_count"] == 1
    assert overview["summary"]["partial_count"] == 1

    detail = svc.get_case_detail(proj, "Q1", env="dev")
    assert detail["case"]["id"] == "Q1"
    assert detail["case"]["eval_review"]["status"] == "PARTIAL"

    # Mutating suite & exporting CSV in SQLite / service data dir MUST NEVER touch target repo
    suite_id = overview["active_suite"]["id"]
    svc.upsert_cases(
        suite_id,
        [{"id": "Q2", "turns": [{"question": "New Q", "expected_answer": "Ans"}]}],
    )
    csv_path = svc.export_csv(proj, env="dev", suite_id=suite_id)
    assert csv_path.is_file()
    assert not str(csv_path).startswith(str(repo.resolve()))

    after_files = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())
    assert after_files == before_files
