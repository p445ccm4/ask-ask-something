from __future__ import annotations

from io import BytesIO
import zipfile
from pathlib import Path
from fastapi.testclient import TestClient

from ask_workbench.config import Settings
from ask_workbench.main import create_app


def _make_minimal_xlsx(rows: list[list[str]]) -> bytes:
    """Create a valid minimal inline-string .xlsx workbook in memory."""
    buf = BytesIO()
    row_xml_parts: list[str] = []
    for r_idx, row in enumerate(rows, 1):
        cells = []
        for c_idx, val in enumerate(row):
            col_letter = chr(ord("A") + c_idx)
            esc = (
                val.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            cells.append(
                f'<c r="{col_letter}{r_idx}" t="inlineStr"><is><t>{esc}</t></is></c>'
            )
        row_xml_parts.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml_parts)}</sheetData>'
        "</worksheet>"
    )
    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="EvalSheet" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def test_fastapi_endpoints_projects_eval_xlsx_and_workbench(tmp_path: Path) -> None:
    dev_repo = tmp_path / "sample-dev"
    uat_repo = tmp_path / "sample-uat"
    (dev_repo / "scripts" / "uat" / "results").mkdir(parents=True)
    (dev_repo / "scripts" / "uat" / "uat_config.json").write_text(
        '{"agent_name": "Sample Agent", "endpoint": "https://example.run.app/chat"}',
        encoding="utf-8",
    )
    (dev_repo / "scripts" / "uat" / "uat_questions.json").write_text(
        '[{"id": "Q1", "turns": [{"question": "Hi", "expected_answer": "Hello"}]}]',
        encoding="utf-8",
    )
    (dev_repo / "scripts" / "uat" / "results" / "uat_results.json").write_text(
        '[{"id": "Q1", "uat_review": {"status": "FAIL", "score": 0.0, "comment": "Mismatch"}, "turns": []}]',
        encoding="utf-8",
    )
    (dev_repo / ".git").mkdir()
    (uat_repo / ".git").mkdir(parents=True)
    (uat_repo / "app.py").write_text("UAT = True\n", encoding="utf-8")

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
    assert names1 == ["data", "notes-dir", "sample-dev", "sample-uat"]
    repo_entry = next(f for f in b1_data["folders"] if f["name"] == "sample-dev")
    assert repo_entry["is_git_repo"] is True
    assert repo_entry["already_added"] is False

    b_hidden = client.get(
        "/projects/browse",
        params={"path": str(tmp_path), "include_hidden": "true"},
    )
    assert b_hidden.status_code == 200
    assert any(f["name"] == ".secret-dir" for f in b_hidden.json()["folders"])

    assert client.get("/projects/browse", params={"path": str(tmp_path / "missing")}).status_code == 400

    add_resp = client.post(
        "/projects",
        json={"name": "Sample", "environments": {"dev": str(dev_repo), "uat": str(uat_repo)}},
    )
    assert add_resp.status_code == 200
    proj = add_resp.json()["project"]
    pid = proj["id"]
    assert proj["active_env"] == "dev"
    assert proj["configured_envs"] == ["dev", "uat"]

    b2 = client.get("/workspaces/browse", params={"path": str(tmp_path)})
    assert b2.status_code == 200
    assert next(f for f in b2.json()["folders"] if f["name"] == "sample-dev")["already_added"] is True

    # Overview & Case Detail (migrated read-only into SQLite)
    ov = client.get(f"/projects/{pid}/eval/overview", params={"env": "dev"})
    assert ov.status_code == 200
    data = ov.json()
    assert data["summary"]["fail_count"] == 1
    assert data["summary"]["failing_ids"] == ["Q1"]
    default_suite_id = data["active_suite"]["id"]

    detail = client.get(f"/projects/{pid}/eval/suites/{default_suite_id}/cases/Q1")
    assert detail.status_code == 200
    assert detail.json()["case"]["eval_review"]["comment"] == "Mismatch"

    # Switch active_env -> uat
    patched = client.patch(f"/projects/{pid}", json={"active_env": "uat"})
    assert patched.status_code == 200
    assert patched.json()["project"]["active_env"] == "uat"

    # Multipart XLSX Inspect & Import into DEV without touching dev_repo
    xlsx_bytes = _make_minimal_xlsx(
        [
            ["Case ID", "Question", "Expected Answer", "Actual Answer", "Status", "Review Comment"],
            ["EX-1", "Policy?", "Yes", "", "", ""],
        ]
    )
    ins = client.post(
        f"/projects/{pid}/eval/inspect-xlsx",
        files={"file": ("hr_eval.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert ins.status_code == 200
    assert ins.json()["sheets"] == ["EvalSheet"]

    imp = client.post(
        f"/projects/{pid}/eval/import-xlsx",
        data={"env": "dev", "suite_name": "HR Excel Suite"},
        files={"file": ("hr_eval.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imp.status_code == 200
    imp_data = imp.json()
    assert imp_data["imported_cases"] == 1
    excel_suite_id = imp_data["suite"]["id"]
    assert imp_data["suite"]["config"]["endpoint"] == "https://example.run.app/chat"
    assert not (dev_repo / "hr_eval.xlsx").exists()

    # Export CSV and updated XLSX
    csv_res = client.get(f"/projects/{pid}/eval/suites/{excel_suite_id}/export-csv")
    assert csv_res.status_code == 200
    assert "EX-1" in csv_res.text

    xlsx_res = client.get(f"/projects/{pid}/eval/suites/{excel_suite_id}/export-xlsx")
    assert xlsx_res.status_code == 200
    assert len(xlsx_res.content) > 100

    # Compare envs & deploy preview
    cmp = client.get(f"/projects/{pid}/compare", params={"source_env": "dev", "target_env": "uat"})
    assert cmp.status_code == 200
    assert cmp.json()["in_sync"] is False

    prev = client.get(f"/projects/{pid}/deploy/preview", params={"target_env": "dev"})
    assert prev.status_code == 200
    assert prev.json()["can_deploy"] is False

    # Conversations, commands, files, artifacts (project-level workspace_id)
    conv = client.post("/conversations", json={"workspace_id": pid, "title": "Debug Q1"})
    assert conv.status_code == 200
    conv_id = conv.json()["conversation"]["conversation_id"]

    convs = client.get("/conversations", params={"workspace_id": pid})
    assert convs.status_code == 200
    assert any(c["conversation_id"] == conv_id for c in convs.json()["conversations"])

    renamed = client.patch(f"/conversations/{conv_id}", json={"title": "  Q1 Root Cause  "})
    assert renamed.status_code == 200
    assert renamed.json()["conversation"]["title"] == "Q1 Root Cause"

    interrupt_idle = client.post(f"/conversations/{conv_id}/interrupt")
    assert interrupt_idle.status_code == 200 and interrupt_idle.json()["ok"] is True

    cmds = client.get("/commands", params={"workspace_id": pid})
    assert cmds.status_code == 200
    cmd_names = {c["name"] for c in cmds.json()["commands"]}
    assert {"plan", "review", "tests", "explain", "ask-ask-something", "generative_ui"}.issubset(cmd_names)

    files = client.get(f"/workspaces/{pid}/files", params={"q": "app"})
    assert files.status_code == 200
    assert any(f["relative_path"] == "app.py" for f in files.json()["files"])

    auth_st = client.get("/auth/status")
    assert auth_st.status_code == 200 and "authenticated" in auth_st.json()

    assert client.post("/approvals/nonexistent", json={"approved": True}).status_code == 404

    from ag_workbench.store import ArtifactRecord

    art_id = "a" * 32
    app.state.conv_store.save_artifact(
        ArtifactRecord(
            artifact_id=art_id,
            conversation_id=conv_id,
            filename="widget.html",
            source_path=".ag-artifacts/widget.html",
            content="<div>ok</div>",
            size_bytes=13,
        )
    )
    assert client.get(f"/artifacts/{art_id}", params={"format": "json"}).json()["content"] == "<div>ok</div>"
    art_raw = client.get(f"/artifacts/{art_id}")
    assert art_raw.headers.get("content-security-policy") == "sandbox"

    assert client.delete(f"/projects/{pid}/eval/suites/{excel_suite_id}").status_code == 200
    assert client.delete(f"/conversations/{conv_id}").status_code == 200
    assert client.get(f"/conversations/{conv_id}").status_code == 404
