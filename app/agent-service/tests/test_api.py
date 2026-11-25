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

    (repo / ".git").mkdir()
    plain_dir = tmp_path / "notes-dir"
    plain_dir.mkdir()
    hidden_dir = tmp_path / ".secret-dir"
    hidden_dir.mkdir()

    settings = Settings(data_dir=tmp_path / "data")
    app = create_app(settings)
    client = TestClient(app)

    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    assert len(h.json()["available_models"]) >= 3
    assert h.json()["web_search"]["available"] is True

    b1 = client.get("/workspaces/browse", params={"path": str(tmp_path)})
    assert b1.status_code == 200
    b1_data = b1.json()
    assert b1_data["current_path"] == str(tmp_path.resolve())
    names1 = [f["name"] for f in b1_data["folders"]]
    assert names1 == ["data", "notes-dir", "sample-agent"]
    repo_entry = next(f for f in b1_data["folders"] if f["name"] == "sample-agent")
    assert repo_entry["is_git_repo"] is True
    assert repo_entry["already_added"] is False

    b_hidden = client.get(
        "/workspaces/browse",
        params={"path": str(tmp_path), "include_hidden": "true"},
    )
    assert b_hidden.status_code == 200
    assert any(f["name"] == ".secret-dir" for f in b_hidden.json()["folders"])

    bad_browse = client.get("/workspaces/browse", params={"path": str(tmp_path / "missing")})
    assert bad_browse.status_code == 400

    add_resp = client.post("/workspaces", json={"name": "Sample", "path": str(repo)})
    assert add_resp.status_code == 200
    ws_id = add_resp.json()["workspace"]["id"]

    b2 = client.get("/workspaces/browse", params={"path": str(tmp_path)})
    assert b2.status_code == 200
    repo_entry2 = next(f for f in b2.json()["folders"] if f["name"] == "sample-agent")
    assert repo_entry2["already_added"] is True

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
    convs_data = convs.json()
    assert any(c["conversation_id"] == conv_id for c in convs_data["conversations"])
    assert convs_data["total"] >= 1
    assert "limit" in convs_data
    assert "offset" in convs_data
    assert "has_more" in convs_data

    renamed = client.patch(f"/conversations/{conv_id}", json={"title": "  Q1 Root Cause  "})
    assert renamed.status_code == 200
    assert renamed.json()["conversation"]["title"] == "Q1 Root Cause"

    interrupt_idle = client.post(f"/conversations/{conv_id}/interrupt")
    assert interrupt_idle.status_code == 200
    assert interrupt_idle.json()["ok"] is True
    assert interrupt_idle.json()["interrupted"] is False

    cmds = client.get("/commands", params={"workspace_id": ws_id})
    assert cmds.status_code == 200
    cmd_names = {c["name"] for c in cmds.json()["commands"]}
    assert {"plan", "review", "tests", "explain", "ask-ask-something", "generative_ui"}.issubset(cmd_names)

    files = client.get(f"/workspaces/{ws_id}/files", params={"q": "uat"})
    assert files.status_code == 200
    file_items = files.json()["files"]
    assert any(f["relative_path"] == "scripts/uat/uat_config.json" and f["kind"] == "file" for f in file_items)
    assert any(f["relative_path"] == "scripts/uat" and f["kind"] == "directory" for f in file_items)

    auth_st = client.get("/auth/status")
    assert auth_st.status_code == 200
    assert "authenticated" in auth_st.json()

    missing_appr = client.post("/approvals/nonexistent", json={"approved": True})
    assert missing_appr.status_code == 404

    cancel_idle = client.post(f"/conversations/{conv_id}/cancel")
    assert cancel_idle.status_code == 200
    assert cancel_idle.json()["ok"] is True
    assert cancel_idle.json()["cancelled"] is False

    deleted = client.delete(f"/conversations/{conv_id}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
    assert deleted.json()["deleted"] is True

    after_del = client.get(f"/conversations/{conv_id}")
    assert after_del.status_code == 404
