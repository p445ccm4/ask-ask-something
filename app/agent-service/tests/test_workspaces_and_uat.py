from __future__ import annotations

import json
from pathlib import Path

from ask_workbench.uat_service import UatService
from ask_workbench.workspaces import WorkspaceEntry, WorkspaceRegistry


def test_workspace_registry_add_and_summarize(tmp_path: Path) -> None:
    repo = tmp_path / "demo-agent"
    (repo / "scripts" / "uat" / "results").mkdir(parents=True)
    (repo / "scripts" / "uat" / "uat_config.json").write_text('{"endpoint": "http://localhost"}')
    (repo / "scripts" / "uat" / "uat_questions.json").write_text('[{"id": "Q1", "turns": []}]')

    reg = WorkspaceRegistry(tmp_path / "workspaces.json", seed_defaults=False)
    assert reg.list_entries() == []

    entry = reg.add_entry(name="Demo Agent", path=str(repo))
    summaries = reg.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].id == entry.id
    assert summaries[0].has_uat_config is True
    assert summaries[0].has_uat_questions is True
    assert summaries[0].has_uat_results is False
    assert summaries[0].uat_path is None

    uat_repo = tmp_path / "demo-agent-uat"
    uat_repo.mkdir()
    updated = reg.add_entry(name="Demo Agent", path=str(repo), uat_path=str(uat_repo))
    assert updated.id == entry.id
    assert updated.uat_path == str(uat_repo.resolve())


def test_workspace_registry_seeds_from_env_json(tmp_path: Path) -> None:
    repo = tmp_path / "seeded-agent"
    repo.mkdir()
    seed_json = json.dumps([{"id": "seeded-dev", "name": "Seeded (DEV)", "path": str(repo), "env": "dev"}])

    reg = WorkspaceRegistry(
        tmp_path / "workspaces.json",
        seed_defaults=True,
        default_workspaces_json=seed_json,
    )
    entries = reg.list_entries()
    assert len(entries) == 1
    assert entries[0].id == "seeded-dev"


def test_read_legacy_scripts_dev_uat_overview(tmp_path: Path) -> None:
    repo = tmp_path / "legacy-agent"
    dev_dir = repo / "scripts" / "dev"
    dev_dir.mkdir(parents=True)
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

    ws = WorkspaceEntry(
        id="legacy-dev",
        name="Legacy Agent (DEV)",
        path=str(repo),
        env="dev",
    )
    svc = UatService()
    overview = svc.get_overview(ws)
    assert overview.has_questions is True
    assert overview.has_results is True
    assert overview.questions_count == 1
    assert overview.summary.partial_count == 1
    detail = svc.get_case_detail(ws, "Q1")
    assert detail["case"]["id"] == "Q1"
