from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from ask_workbench.config import Settings
from ask_workbench.main import create_app


def test_fastapi_endpoints_with_temp_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "sample-agent"
    (repo / "scripts" / "uat" / "results").mkdir(parents=True)
    (repo / "scripts" / "uat" / "uat_config.json").write_text(
        '{"agent_name": "Sample Agent", "endpoint": "https://example.run.app/chat"}',
        encoding="utf-8",
    )
    (repo / "scripts" / "uat" / "uat_questions.json").write_text(
        '[{"id": "Q1", "turns": [{"question": "Hi", "expected_answer": "Hello"}]}]',
        encoding="utf-8",
    )
    (repo / "scripts" / "uat" / "results" / "uat_results.json").write_text(
        '[{"id": "Q1", "uat_review": {"status": "FAIL", "score": 0.0, "comment": "Mismatch"}, "turns": []}]',
        encoding="utf-8",
    )

    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    client = TestClient(app)

    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    assert len(h.json()["available_models"]) >= 3

    add_resp = client.post("/workspaces", json={"name": "Sample", "path": str(repo)})
    assert add_resp.status_code == 200
    ws_id = add_resp.json()["workspace"]["id"]

    ov = client.get(f"/workspaces/{ws_id}/uat/overview")
    assert ov.status_code == 200
    data = ov.json()
    assert data["summary"]["fail_count"] == 1
    assert data["summary"]["failing_ids"] == ["Q1"]

    prev = client.get(f"/workspaces/{ws_id}/deploy/preview", params={"target_env": "dev"})
    assert prev.status_code == 200
    assert prev.json()["can_deploy"] is False

    conv = client.post("/conversations", json={"workspace_id": ws_id, "title": "Debug Q1"})
    assert conv.status_code == 200
    conv_id = conv.json()["conversation"]["conversation_id"]

    convs = client.get("/conversations", params={"workspace_id": ws_id})
    assert convs.status_code == 200
    assert any(c["conversation_id"] == conv_id for c in convs.json()["conversations"])

    missing_appr = client.post("/approvals/nonexistent", json={"approved": True})
    assert missing_appr.status_code == 404

    cancel_idle = client.post(f"/conversations/{conv_id}/cancel")
    assert cancel_idle.status_code == 200
    assert cancel_idle.json()["ok"] is True
    assert cancel_idle.json()["cancelled"] is False
