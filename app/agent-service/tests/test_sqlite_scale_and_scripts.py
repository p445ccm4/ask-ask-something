from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path

from ask_workbench.ask_workbench_db import AskWorkbenchDB
from ask_workbench.config import SKILL_SCRIPTS_DIR
from ask_workbench.uat_service import EvalRunRequest, EvalService
from ask_workbench.workspaces import ProjectRegistry


def _make_workbook(path: Path) -> None:
    buf = BytesIO()
    rows = [
        ["Case ID", "Question", "Expected Answer", "Actual Answer", "Actual Sources", "Status", "Review Comment"],
        ["E1", "What is annual leave?", "18 days", "", "", "", ""],
        ["", "Can I carry it over?", "Yes up to 5 days", "", "", "", ""],
        ["E2", "What is sick leave?", "12 days", "", "", "", ""],
    ]
    row_xml: list[str] = []
    for r_idx, row in enumerate(rows, 1):
        cells = []
        for c_idx, val in enumerate(row):
            col_l = chr(ord("A") + c_idx)
            cells.append(f'<c r="{col_l}{r_idx}" t="inlineStr"><is><t>{val}</t></is></c>')
        row_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="QA" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>',
        )
    path.write_bytes(buf.getvalue())


def test_sqlite_pagination_for_550_eval_suites(tmp_path: Path) -> None:
    db = AskWorkbenchDB(tmp_path / "scale.db")
    repo = tmp_path / "repo"
    repo.mkdir()
    proj = db.create_project("AskHR", {"dev": str(repo)}, project_id="askhr")

    t0 = time.perf_counter()
    for idx in range(550):
        db.upsert_suite(
            proj["id"],
            "dev",
            f"Suite {idx:03d} {'Policy' if idx % 10 == 0 else 'General'}",
            slug=f"suite-{idx:03d}",
            config={"endpoint": f"https://askhr.run.app/s{idx}"},
        )
    elapsed_insert = time.perf_counter() - t0
    assert elapsed_insert < 5.0

    page1 = db.list_suites(proj["id"], "dev", limit=50, offset=0)
    assert page1["total"] == 550
    assert len(page1["suites"]) == 50
    assert page1["has_more"] is True

    filtered = db.list_suites(proj["id"], "dev", search="Policy", limit=100, offset=0)
    assert filtered["total"] == 55
    assert len(filtered["suites"]) == 55


def test_skill_scripts_db_mode_import_run_replay_and_export(tmp_path: Path) -> None:
    repo = tmp_path / "target-svc"
    repo.mkdir()
    (repo / "marker.txt").write_text("service", encoding="utf-8")

    db_path = tmp_path / "workbench.db"
    db = AskWorkbenchDB(db_path)
    reg = ProjectRegistry(db, seed_defaults=False)
    proj = reg.add_project("MockBot", environments={"dev": str(repo)})

    xlsx_in = tmp_path / "cases.xlsx"
    _make_workbook(xlsx_in)

    xlsx_script = SKILL_SCRIPTS_DIR / "xlsx_to_uat.py"
    run_script = SKILL_SCRIPTS_DIR / "run_uat_batch.py"

    # 1. Import .xlsx directly into SQLite DB with --group-blank-id
    subprocess.run(
        [
            sys.executable,
            str(xlsx_script),
            "import",
            str(xlsx_in),
            "--db",
            str(db_path),
            "--project",
            proj.id,
            "--env",
            "dev",
            "--suite-name",
            "CLI Imported Suite",
            "--group-blank-id",
        ],
        check=True,
    )

    suites = db.list_suites(proj.id, "dev")
    assert suites["total"] == 1
    suite_id = suites["suites"][0]["id"]
    cases_page = db.query_cases(suite_id)
    assert cases_page["total"] == 2
    assert next(c for c in cases_page["cases"] if c["id"] == "E1")["turn_count"] == 2

    # 2. Start a tiny local HTTP mock agent server and configure endpoint in SQLite
    seen_questions: list[str] = []

    class _MockHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            msgs = body.get("contents") or body.get("messages") or []
            last_q = str(msgs[-1]) if msgs else ""
            seen_questions.append(last_q)
            resp = json.dumps({"answer": f"Mock reply ({len(msgs)} msgs)", "sources": ["doc.pdf"]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        db.upsert_suite(
            proj.id,
            "dev",
            "CLI Imported Suite",
            suite_id=suite_id,
            config={
                "agent_name": "MockBot",
                "endpoint": f"http://127.0.0.1:{port}/chat",
                "auth": {"mode": "none"},
                "request": {"format": "simple-chat"},
                "response": {"mode": "json", "text_field": "answer", "sources_field": "sources"},
                "concurrency": 2,
            },
        )

        # 3. Run batch via CLI in --db --no-eval mode (writes to SQLite, zero writes to target repo)
        db.create_run(
            job_id="job_full",
            project_id=proj.id,
            env="dev",
            suite_id=suite_id,
            endpoint=f"http://127.0.0.1:{port}/chat",
        )
        subprocess.run(
            [
                sys.executable,
                str(run_script),
                "--db",
                str(db_path),
                "--suite-id",
                suite_id,
                "--job-id",
                "job_full",
                "--no-eval",
            ],
            cwd=str(repo),
            check=True,
        )

        detail_e1 = db.get_case_detail(suite_id, "E1")
        assert len(detail_e1["turns"]) == 2
        assert "Mock reply" in detail_e1["turns"][0]["raw_response"]["text"]
        assert detail_e1["turns"][1]["raw_response"]["sources"] == ["doc.pdf"]

        # 4. Turn 2 replay for --id E1 --turn 2 should replay turn 1 from DB without hitting server for Turn 1!
        seen_questions.clear()
        subprocess.run(
            [
                sys.executable,
                str(run_script),
                "--db",
                str(db_path),
                "--suite-id",
                suite_id,
                "--id",
                "E1",
                "--turn",
                "2",
                "--no-eval",
            ],
            cwd=str(repo),
            check=True,
        )
        assert len(seen_questions) == 1  # Only Turn 2 hit the HTTP server; Turn 1 replayed from DB

        # 5. Export back to .xlsx and .csv from DB
        out_xlsx = tmp_path / "updated.xlsx"
        out_csv = tmp_path / "exported.csv"
        subprocess.run(
            [
                sys.executable,
                str(xlsx_script),
                "update-xlsx",
                str(xlsx_in),
                "--db",
                str(db_path),
                "--suite-id",
                suite_id,
                "--group-blank-id",
                "-o",
                str(out_xlsx),
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(xlsx_script),
                "export",
                "--db",
                str(db_path),
                "--suite-id",
                suite_id,
                "-o",
                str(out_csv),
            ],
            check=True,
        )
        assert out_xlsx.is_file()
        assert "Mock reply" in out_csv.read_text(encoding="utf-8")

        # Verify EvalService.run_and_collect builds valid --db command
        svc = EvalService(db, templates_dir=tmp_path / "tmpl", exports_dir=tmp_path / "exp")
        cmd, resolved_env, _ = svc.build_run_command(
            proj, EvalRunRequest(suite_id=suite_id, case_ids="E1", no_eval=True), job_id="job_svc"
        )
        assert "--db" in cmd and "--suite-id" in cmd and resolved_env == "dev"

        # Zero files written inside target repo!
        repo_files = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file())
        assert repo_files == ["marker.txt"]
    finally:
        server.shutdown()
        server.server_close()
