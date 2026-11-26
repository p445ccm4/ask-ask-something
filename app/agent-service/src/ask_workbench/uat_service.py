from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field

from .ask_workbench_db import VALID_ENVS, AskWorkbenchDB, EnvName
from .config import SKILL_SCRIPTS_DIR, get_settings
from .workspaces import ProjectEntry, WorkspaceEntry


def _as_project(project_or_ws: ProjectEntry | WorkspaceEntry) -> ProjectEntry:
    if isinstance(project_or_ws, ProjectEntry):
        return project_or_ws
    return project_or_ws.to_project_entry()


def _load_xlsx_module(script_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("ask_xlsx_tool", str(script_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load xlsx helper from {script_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EvalRunRequest(BaseModel):
    suite_id: str | None = None
    case_ids: str = ""
    turn: int | None = None
    runs: int = 1
    limit: int | None = None
    no_eval: bool = False
    concurrency: int | None = None
    env: EnvName | None = None
    repo: EnvName | None = None


UatRunRequest = EvalRunRequest


class EvalSummaryStats(BaseModel):
    total_cases: int = 0
    evaluated_cases: int = 0
    pass_count: int = 0
    partial_count: int = 0
    fail_count: int = 0
    total_score: float = 0.0
    score_pct: float = 0.0
    failing_ids: list[str] = Field(default_factory=list)
    updated_at: float | None = None


UatSummaryStats = EvalSummaryStats


@dataclass
class EvalJob:
    job_id: str
    project_id: str
    env: EnvName
    suite_id: str
    command: list[str]
    status: str = "running"  # running, completed, failed
    exit_code: int | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lines: list[str] = field(default_factory=list)
    _subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            q.put_nowait(event)


UatJob = EvalJob


def compute_summary(results: list[dict[str, Any]]) -> EvalSummaryStats:
    pass_cnt = 0
    partial_cnt = 0
    fail_cnt = 0
    total_score = 0.0
    failing_ids: list[str] = []

    for item in results:
        rev = item.get("uat_review") or item.get("eval_review") or {}
        status = str(rev.get("status") or "").upper()
        score = float(rev.get("score") or 0.0)
        total_score += score
        if status == "PASS":
            pass_cnt += 1
        elif status == "PARTIAL":
            partial_cnt += 1
            failing_ids.append(str(item.get("id", "")))
        elif status == "FAIL":
            fail_cnt += 1
            failing_ids.append(str(item.get("id", "")))

    evaluated = len(results)
    pct = round((total_score / evaluated) * 100, 1) if evaluated else 0.0
    return EvalSummaryStats(
        total_cases=evaluated,
        evaluated_cases=evaluated,
        pass_count=pass_cnt,
        partial_count=partial_cnt,
        fail_count=fail_cnt,
        total_score=round(total_score, 2),
        score_pct=pct,
        failing_ids=[fid for fid in failing_ids if fid],
    )


class EvalService:
    """SQLite-backed Eval Suite, Excel import/export, and batch execution service."""

    def __init__(
        self,
        db: AskWorkbenchDB | None = None,
        *,
        scripts_dir: Path | None = None,
        templates_dir: Path | None = None,
        exports_dir: Path | None = None,
    ) -> None:
        cfg = get_settings()
        self._db = db or AskWorkbenchDB(cfg.workbench_db_file)
        self._scripts_dir = scripts_dir or SKILL_SCRIPTS_DIR
        self._templates_dir = Path(templates_dir or cfg.templates_dir)
        self._exports_dir = Path(exports_dir or cfg.exports_dir)
        self._jobs: dict[str, EvalJob] = {}
        self._xlsx_mod: ModuleType | None = None

    @property
    def db(self) -> AskWorkbenchDB:
        return self._db

    @property
    def run_batch_script(self) -> Path:
        return self._scripts_dir / "run_uat_batch.py"

    @property
    def xlsx_script(self) -> Path:
        return self._scripts_dir / "xlsx_to_uat.py"

    def _xlsx_helpers(self) -> ModuleType:
        if self._xlsx_mod is None:
            self._xlsx_mod = _load_xlsx_module(self.xlsx_script)
        return self._xlsx_mod

    @staticmethod
    def _resolve_env(proj: ProjectEntry, env: EnvName | str | None = None) -> EnvName:
        chosen = (env or proj.active_env).lower()
        if chosen not in VALID_ENVS:
            raise ValueError(f"Unsupported environment '{chosen}'. Expected one of {', '.join(VALID_ENVS)}.")
        if chosen not in proj.environments or not proj.environments[chosen].strip():
            raise ValueError(
                f"No {chosen.upper()} repository path is configured for project '{proj.name}'."
            )
        return chosen  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Read-only Legacy Import (never writes to target repo)
    # ------------------------------------------------------------------
    @staticmethod
    def _discover_legacy_paths(repo_path: Path) -> dict[str, Path]:
        uat_dir = repo_path / "scripts" / "uat"
        dev_dir = repo_path / "scripts" / "dev"

        base_dir = uat_dir
        if not (uat_dir / "uat_questions.json").is_file() and (
            (dev_dir / "uat_questions_full.json").is_file()
            or (dev_dir / "uat_questions.json").is_file()
            or (dev_dir / "uat_results.json").is_file()
        ):
            base_dir = dev_dir

        cfg_path = base_dir / "uat_config.json"
        if not cfg_path.is_file() and (uat_dir / "uat_config.json").is_file():
            cfg_path = uat_dir / "uat_config.json"

        q_path = base_dir / "uat_questions.json"
        if not q_path.is_file() and (base_dir / "uat_questions_full.json").is_file():
            q_path = base_dir / "uat_questions_full.json"

        rubric_path = base_dir / "judge_rubric.md"
        if not rubric_path.is_file() and (uat_dir / "judge_rubric.md").is_file():
            rubric_path = uat_dir / "judge_rubric.md"

        mapping_path = base_dir / "excel_mapping.json"
        if not mapping_path.is_file() and (uat_dir / "excel_mapping.json").is_file():
            mapping_path = uat_dir / "excel_mapping.json"

        results_path = base_dir / "results" / "uat_results.json"
        if not results_path.is_file() and (base_dir / "uat_results.json").is_file():
            results_path = base_dir / "uat_results.json"

        return {
            "base_dir": base_dir,
            "config": cfg_path,
            "questions": q_path,
            "rubric": rubric_path,
            "mapping": mapping_path,
            "results": results_path,
        }

    def import_legacy_from_repo(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        only_if_empty: bool = True,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        if only_if_empty:
            existing = self._db.list_suites(proj.id, target_env, limit=1, offset=0)
            if existing["total"] > 0:
                return {"imported": False, "reason": "already_exists"}

        ws = Path(proj.path_for_env(target_env)).expanduser()
        if not ws.is_dir():
            return {"imported": False, "reason": "directory_missing"}

        paths = self._discover_legacy_paths(ws)
        has_any = any(
            paths[k].is_file()
            for k in ("config", "questions", "rubric", "mapping", "results")
        )
        if not has_any:
            return {"imported": False, "reason": "no_legacy_files"}

        cfg: dict[str, Any] = {}
        if paths["config"].is_file():
            try:
                loaded = json.loads(paths["config"].read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    cfg = loaded
            except json.JSONDecodeError:
                pass

        rubric_md = ""
        if paths["rubric"].is_file():
            rubric_md = paths["rubric"].read_text(encoding="utf-8")
        elif cfg and isinstance((cfg.get("judge") or {}).get("rubric_file"), str):
            rf = Path(cfg["judge"]["rubric_file"])
            cand = rf if rf.is_absolute() else (paths["base_dir"] / rf)
            if cand.is_file():
                rubric_md = cand.read_text(encoding="utf-8")

        excel_mapping: dict[str, Any] = {}
        if paths["mapping"].is_file():
            try:
                loaded_m = json.loads(paths["mapping"].read_text(encoding="utf-8"))
                if isinstance(loaded_m, dict):
                    excel_mapping = loaded_m
            except json.JSONDecodeError:
                pass

        questions: list[dict[str, Any]] = []
        if paths["questions"].is_file():
            try:
                loaded_q = json.loads(paths["questions"].read_text(encoding="utf-8"))
                if isinstance(loaded_q, list):
                    questions = [q for q in loaded_q if isinstance(q, dict)]
            except json.JSONDecodeError:
                pass

        results: list[dict[str, Any]] = []
        if paths["results"].is_file():
            try:
                loaded_r = json.loads(paths["results"].read_text(encoding="utf-8"))
                if isinstance(loaded_r, list):
                    results = [r for r in loaded_r if isinstance(r, dict)]
            except json.JSONDecodeError:
                pass

        if not questions and results:
            for item in results:
                cid = str(item.get("id") or "").strip()
                if not cid:
                    continue
                turns = item.get("turns") if isinstance(item.get("turns"), list) else []
                questions.append(
                    {
                        "id": cid,
                        "turns": [
                            {
                                "question": str(t.get("question") or f"Case {cid} Turn {idx}"),
                                "expected_answer": str(t.get("expected_answer") or ""),
                                "expected_behavior": str(t.get("expected_behavior") or ""),
                            }
                            for idx, t in enumerate(turns, 1)
                            if isinstance(t, dict)
                        ]
                        or [{"question": f"Case {cid}", "expected_answer": "", "expected_behavior": ""}],
                    }
                )

        suite_name = str(cfg.get("agent_name") or "").strip() or f"{proj.name} ({target_env.upper()}) Eval"
        suite = self._db.upsert_suite(
            proj.id,
            target_env,
            suite_name,
            slug="default",
            description=f"Imported read-only from legacy {paths['base_dir'].relative_to(ws)}",
            config=cfg,
            rubric_md=rubric_md,
            excel_mapping=excel_mapping,
            is_default=True,
        )
        cases_cnt = self._db.upsert_cases(suite["id"], questions, replace_all=False)
        res_cnt = 0
        for item in results:
            cid = str(item.get("id") or "").strip()
            if cid:
                self._db.record_case_result(suite_id=suite["id"], case_id=cid, record=item, job_id=None)
                res_cnt += 1

        return {
            "imported": True,
            "suite_id": suite["id"],
            "cases_count": cases_cnt,
            "results_count": res_cnt,
        }

    def ensure_env_seeded(self, proj: ProjectEntry, env: EnvName) -> None:
        existing = self._db.list_suites(proj.id, env, limit=1, offset=0)
        if existing["total"] == 0:
            self.import_legacy_from_repo(proj, env, only_if_empty=True)

    # ------------------------------------------------------------------
    # Suites & Cases CRUD / Queries
    # ------------------------------------------------------------------
    def list_suites(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        self.ensure_env_seeded(proj, target_env)
        return self._db.list_suites(
            proj.id,
            target_env,
            search=search,
            limit=limit,
            offset=offset,
        )

    def _resolve_suite(
        self,
        proj: ProjectEntry,
        env: EnvName,
        suite_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.ensure_env_seeded(proj, env)
        if suite_id and suite_id.strip():
            suite = self._db.get_suite(suite_id.strip())
            if suite["project_id"] != proj.id or suite["env"] != env:
                raise KeyError(
                    f"Eval suite '{suite_id}' does not belong to {proj.name} ({env.upper()})."
                )
            return suite
        return self._db.get_default_or_first_suite(proj.id, env)

    def create_or_update_suite(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        suite_id: str | None = None,
        name: str = "New Eval Suite",
        slug: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        rubric_md: str | None = None,
        excel_mapping: dict[str, Any] | None = None,
        is_default: bool | None = None,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        return self._db.upsert_suite(
            proj.id,
            target_env,
            name,
            suite_id=suite_id,
            slug=slug,
            description=description,
            config=config,
            rubric_md=rubric_md,
            excel_mapping=excel_mapping,
            is_default=is_default,
        )

    def delete_suite(self, suite_id: str) -> bool:
        tmpl = self._templates_dir / f"{suite_id}.xlsx"
        if tmpl.is_file():
            tmpl.unlink(missing_ok=True)
        return self._db.delete_suite(suite_id)

    def get_overview(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        repo: EnvName | str | None = None,
        suite_id: str | None = None,
        status: str = "ALL",
        turn_filter: str = "ALL",
        search: str = "",
        sort_by: str = "ORDER",
        limit: int = 200,
        offset: int = 0,
        include_details: bool = False,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env or repo)
        suite = self._resolve_suite(proj, target_env, suite_id=suite_id)
        suites_page = self._db.list_suites(proj.id, target_env, limit=50, offset=0)

        if not suite:
            return {
                "project_id": proj.id,
                "project_name": proj.name,
                "env": target_env,
                "workspace_id": proj.id,
                "workspace_name": proj.name,
                "repo": target_env,
                "suites_total": suites_page["total"],
                "suites": suites_page["suites"],
                "active_suite": None,
                "has_config": False,
                "has_questions": False,
                "has_results": False,
                "has_template_xlsx": False,
                "config": None,
                "rubric_preview": "",
                "questions_count": 0,
                "summary": EvalSummaryStats().model_dump(),
                "cases": [],
                "cases_total": 0,
                "cases_has_more": False,
                "runs": [],
                "results_updated_at": None,
            }

        summary_raw = self._db.get_suite_summary(suite["id"])
        cases_page = self._db.query_cases(
            suite["id"],
            status=status,
            turn_filter=turn_filter,
            search=search,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
            include_details=include_details,
        )
        runs = self._db.list_runs(suite["id"], limit=15)
        cfg = suite.get("config") or {}
        has_template = (self._templates_dir / f"{suite['id']}.xlsx").is_file()

        return {
            "project_id": proj.id,
            "project_name": proj.name,
            "env": target_env,
            "workspace_id": proj.id,
            "workspace_name": proj.name,
            "repo": target_env,
            "suites_total": suites_page["total"],
            "suites": suites_page["suites"],
            "active_suite": {
                "id": suite["id"],
                "slug": suite["slug"],
                "name": suite["name"],
                "description": suite["description"],
                "endpoint": str(cfg.get("endpoint") or ""),
                "source_xlsx_name": suite["source_xlsx_name"],
                "is_default": suite["is_default"],
                "has_template_xlsx": has_template,
                "excel_mapping": suite.get("excel_mapping") or {},
                "updated_at": suite["updated_at"],
            },
            "has_config": bool(cfg.get("endpoint")),
            "has_questions": summary_raw["total_cases"] > 0,
            "has_results": summary_raw["evaluated_cases"] > 0,
            "has_template_xlsx": has_template,
            "config": cfg,
            "rubric_preview": suite.get("rubric_md") or "",
            "questions_count": summary_raw["total_cases"],
            "summary": summary_raw,
            "cases": cases_page["cases"],
            "cases_total": cases_page["total"],
            "cases_has_more": cases_page["has_more"],
            "runs": runs,
            "results_updated_at": summary_raw.get("updated_at"),
        }

    def query_cases(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        suite_id: str | None = None,
        status: str = "ALL",
        turn_filter: str = "ALL",
        search: str = "",
        sort_by: str = "ORDER",
        limit: int = 200,
        offset: int = 0,
        include_details: bool = False,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        suite = self._resolve_suite(proj, target_env, suite_id=suite_id)
        if not suite:
            return {"cases": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}
        res = self._db.query_cases(
            suite["id"],
            status=status,
            turn_filter=turn_filter,
            search=search,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
            include_details=include_details,
        )
        res["suite_id"] = suite["id"]
        return res

    def get_case_detail(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        case_id: str,
        env: EnvName | str | None = None,
        *,
        repo: EnvName | str | None = None,
        suite_id: str | None = None,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env or repo)
        suite = self._resolve_suite(proj, target_env, suite_id=suite_id)
        if not suite:
            raise KeyError(
                f"No eval suite found in {target_env.upper()} environment of project '{proj.name}'."
            )
        detail = self._db.get_case_detail(suite["id"], case_id)
        return {
            "found_in": "sqlite",
            "env": target_env,
            "repo": target_env,
            "suite_id": suite["id"],
            "suite_name": suite["name"],
            "case": detail,
        }

    def upsert_cases(
        self,
        suite_id: str,
        cases: list[dict[str, Any]],
        *,
        replace_all: bool = False,
    ) -> int:
        return self._db.upsert_cases(suite_id, cases, replace_all=replace_all)

    def delete_case(self, suite_id: str, case_id: str) -> bool:
        return self._db.delete_case(suite_id, case_id)

    # ------------------------------------------------------------------
    # Excel (.xlsx) Inspection, Import & Export (No Target Repo Writes)
    # ------------------------------------------------------------------
    def inspect_xlsx_bytes(
        self,
        content: bytes,
        filename: str = "upload.xlsx",
        *,
        sheet_name: str | None = None,
    ) -> dict[str, Any]:
        mod = self._xlsx_helpers()
        with tempfile.TemporaryDirectory(prefix="ask_xlsx_ins_") as tmpd:
            tmp_path = Path(tmpd) / Path(filename or "upload.xlsx").name
            tmp_path.write_bytes(content)
            info = mod.inspect_workbook(tmp_path, sheet_name=sheet_name)
            suggested = mod.auto_detect_mapping(tmp_path, sheet_name=sheet_name)
        return {
            "filename": Path(filename or "upload.xlsx").name,
            "sheets": info["sheets"],
            "details": info["details"],
            "suggested_mapping": suggested,
        }

    def import_xlsx_bytes(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        content: bytes,
        filename: str,
        suite_name: str | None = None,
        suite_id: str | None = None,
        mapping: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        rubric_md: str | None = None,
        replace_all: bool = True,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        self.ensure_env_seeded(proj, target_env)

        mod = self._xlsx_helpers()
        safe_name = Path(filename or "eval_suite.xlsx").name

        with tempfile.TemporaryDirectory(prefix="ask_xlsx_imp_") as tmpd:
            tmp_path = Path(tmpd) / safe_name
            tmp_path.write_bytes(content)
            chosen_sheet, resolved_cfg, cases, skipped_empty = mod.parse_xlsx_cases(
                tmp_path, mapping
            )

        # For new suites without explicit config/rubric, inherit endpoint config/rubric from existing default suite
        inherited_cfg = config
        inherited_rubric = rubric_md
        if inherited_cfg is None or inherited_rubric is None:
            fallback_suite = self._db.get_default_or_first_suite(proj.id, target_env)
            if fallback_suite and not suite_id:
                if inherited_cfg is None:
                    inherited_cfg = fallback_suite.get("config") or {}
                if inherited_rubric is None:
                    inherited_rubric = fallback_suite.get("rubric_md") or ""

        display_name = (suite_name or "").strip() or Path(safe_name).stem
        suite = self._db.upsert_suite(
            proj.id,
            target_env,
            display_name,
            suite_id=suite_id,
            config=inherited_cfg,
            rubric_md=inherited_rubric,
            excel_mapping=resolved_cfg,
            source_xlsx_name=safe_name,
        )

        # Store uploaded template safely inside agent-service/.data/templates/
        self._templates_dir.mkdir(parents=True, exist_ok=True)
        (self._templates_dir / f"{suite['id']}.xlsx").write_bytes(content)

        imported_cnt = self._db.upsert_cases(suite["id"], cases, replace_all=replace_all)
        total_turns = sum(len(c.get("turns") or []) for c in cases)
        summary = self._db.get_suite_summary(suite["id"])

        return {
            "suite": suite,
            "sheet": chosen_sheet,
            "excel_mapping": resolved_cfg,
            "imported_cases": imported_cnt,
            "total_turns": total_turns,
            "skipped_empty_rows": skipped_empty,
            "summary": summary,
        }

    def export_csv(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        suite_id: str | None = None,
    ) -> Path:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        suite = self._resolve_suite(proj, target_env, suite_id=suite_id)
        if not suite:
            raise FileNotFoundError(f"No eval suite found for {proj.name} ({target_env.upper()}).")

        records = self._db.list_full_results_for_export(suite["id"])
        self._exports_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._exports_dir / f"{suite['id']}.csv"
        mod = self._xlsx_helpers()
        mod.export_records_to_csv(records, out_path)
        return out_path

    def export_xlsx(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        env: EnvName | str | None = None,
        *,
        suite_id: str | None = None,
    ) -> Path:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, env)
        suite = self._resolve_suite(proj, target_env, suite_id=suite_id)
        if not suite:
            raise FileNotFoundError(f"No eval suite found for {proj.name} ({target_env.upper()}).")

        template_path = self._templates_dir / f"{suite['id']}.xlsx"
        if not template_path.is_file():
            raise FileNotFoundError(
                "No .xlsx template is stored for this eval suite. Re-import the original .xlsx or use Export CSV."
            )

        records = self._db.list_full_results_for_export(suite["id"])
        mapping = suite.get("excel_mapping") or None
        self._exports_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._exports_dir / f"{suite['id']}_updated.xlsx"
        mod = self._xlsx_helpers()
        mod.update_xlsx_from_records(template_path, records, out_path, mapping)
        return out_path

    # ------------------------------------------------------------------
    # Eval Batch Execution & Live SSE Log Streaming
    # ------------------------------------------------------------------
    def build_run_command(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        req: EvalRunRequest,
        *,
        job_id: str | None = None,
    ) -> tuple[list[str], EnvName, dict[str, Any]]:
        proj = _as_project(project_or_ws)
        target_env = self._resolve_env(proj, req.env or req.repo)
        suite = self._resolve_suite(proj, target_env, suite_id=req.suite_id)
        if not suite:
            raise FileNotFoundError(
                f"No eval suite found in {target_env.upper()} environment of project '{proj.name}'."
            )
        cfg = suite.get("config") or {}
        if not str(cfg.get("endpoint") or "").strip():
            raise ValueError(
                f"Eval suite '{suite['name']}' is missing an endpoint URL. Configure Endpoint in Suite Settings."
            )
        summary = self._db.get_suite_summary(suite["id"])
        if summary["total_cases"] <= 0:
            raise ValueError(
                f"Eval suite '{suite['name']}' has no eval cases. Import an .xlsx workbook or add cases first."
            )

        cmd = [
            sys.executable,
            "-u",
            str(self.run_batch_script),
            "--db",
            str(self._db.db_path),
            "--suite-id",
            suite["id"],
        ]
        if job_id:
            cmd.extend(["--job-id", job_id])
        if req.case_ids.strip():
            cmd.extend(["--id", req.case_ids.strip()])
        if req.turn is not None:
            cmd.extend(["--turn", str(req.turn)])
        if req.runs > 1:
            cmd.extend(["--runs", str(req.runs)])
        if req.limit is not None and req.limit > 0:
            cmd.extend(["--limit", str(req.limit)])
        if req.concurrency is not None and req.concurrency > 0:
            cmd.extend(["--concurrency", str(req.concurrency)])
        if req.no_eval:
            cmd.append("--no-eval")

        return cmd, target_env, suite

    async def start_run_job(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        req: EvalRunRequest,
    ) -> EvalJob:
        proj = _as_project(project_or_ws)
        job_id = f"eval_{uuid4().hex[:10]}"
        cmd, target_env, suite = self.build_run_command(proj, req, job_id=job_id)
        repo_cwd = Path(proj.path_for_env(target_env)).expanduser()
        if not repo_cwd.is_dir():
            raise FileNotFoundError(f"{target_env.upper()} directory not found: {repo_cwd}")

        endpoint = str((suite.get("config") or {}).get("endpoint") or "")
        self._db.create_run(
            job_id=job_id,
            project_id=proj.id,
            env=target_env,
            suite_id=suite["id"],
            endpoint=endpoint,
            command=cmd,
        )

        job = EvalJob(
            job_id=job_id,
            project_id=proj.id,
            env=target_env,
            suite_id=suite["id"],
            command=cmd,
        )
        self._jobs[job_id] = job
        asyncio.create_task(self._execute_job(job, repo_cwd))
        return job

    async def _execute_job(self, job: EvalJob, cwd: Path) -> None:
        seq = 0
        try:
            proc = await asyncio.create_subprocess_exec(
                *job.command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                seq += 1
                job.lines.append(line)
                self._db.append_run_log(job.job_id, seq, line)
                job.publish({"type": "log", "line": line})

            rc = await proc.wait()
            job.exit_code = rc
            job.status = "completed" if rc == 0 else "failed"
            job.finished_at = time.time()
            summary = self._db.get_suite_summary(job.suite_id)
            self._db.finish_run(
                job.job_id,
                status=job.status,
                exit_code=rc,
                summary=summary,
            )
            job.publish(
                {
                    "type": "done",
                    "status": job.status,
                    "exit_code": rc,
                    "suite_id": job.suite_id,
                    "summary": summary,
                }
            )
        except Exception as exc:  # pragma: no cover
            job.status = "failed"
            job.exit_code = -1
            job.finished_at = time.time()
            err_line = f"ERROR: {exc}"
            seq += 1
            job.lines.append(err_line)
            self._db.append_run_log(job.job_id, seq, err_line)
            self._db.finish_run(job.job_id, status="failed", exit_code=-1)
            job.publish({"type": "log", "line": err_line})
            job.publish({"type": "done", "status": "failed", "exit_code": -1, "suite_id": job.suite_id})

    def get_job(self, job_id: str) -> EvalJob:
        if job_id in self._jobs:
            return self._jobs[job_id]
        run_rec = self._db.get_run(job_id)
        logs = self._db.get_run_logs(job_id)
        return EvalJob(
            job_id=run_rec["job_id"],
            project_id=run_rec["project_id"],
            env=run_rec["env"],
            suite_id=run_rec["suite_id"],
            command=run_rec["command"],
            status=run_rec["status"],
            exit_code=run_rec["exit_code"],
            started_at=run_rec["started_at"],
            finished_at=run_rec["finished_at"],
            lines=logs,
        )

    async def stream_job(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        if job_id not in self._jobs:
            job = self.get_job(job_id)
            for line in job.lines:
                yield {"type": "log", "line": line}
            yield {
                "type": "done",
                "status": job.status,
                "exit_code": job.exit_code,
                "suite_id": job.suite_id,
            }
            return

        job = self._jobs[job_id]
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        job._subscribers.add(q)
        try:
            for line in list(job.lines):
                yield {"type": "log", "line": line}
            if job.status != "running":
                yield {
                    "type": "done",
                    "status": job.status,
                    "exit_code": job.exit_code,
                    "suite_id": job.suite_id,
                }
                return
            while True:
                ev = await q.get()
                yield ev
                if ev.get("type") == "done":
                    break
        finally:
            job._subscribers.discard(q)

    def get_run_logs(self, job_id: str) -> dict[str, Any]:
        run_rec = self._db.get_run(job_id)
        lines = (
            list(self._jobs[job_id].lines)
            if job_id in self._jobs
            else self._db.get_run_logs(job_id)
        )
        return {**run_rec, "lines": lines}

    async def run_and_collect(
        self,
        project_or_ws: ProjectEntry | WorkspaceEntry,
        req: EvalRunRequest,
    ) -> dict[str, Any]:
        proj = _as_project(project_or_ws)
        job_id = f"eval_{uuid4().hex[:10]}"
        cmd, target_env, suite = self.build_run_command(proj, req, job_id=job_id)
        repo_cwd = Path(proj.path_for_env(target_env)).expanduser()
        if not repo_cwd.is_dir():
            raise FileNotFoundError(f"{target_env.upper()} directory not found: {repo_cwd}")

        endpoint = str((suite.get("config") or {}).get("endpoint") or "")
        self._db.create_run(
            job_id=job_id,
            project_id=proj.id,
            env=target_env,
            suite_id=suite["id"],
            endpoint=endpoint,
            command=cmd,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(repo_cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout_bytes, _ = await proc.communicate()
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        for idx, ln in enumerate(stdout_text.splitlines(), 1):
            self._db.append_run_log(job_id, idx, ln)

        rc = proc.returncode
        summary = self._db.get_suite_summary(suite["id"])
        self._db.finish_run(
            job_id,
            status="completed" if rc == 0 else "failed",
            exit_code=rc,
            summary=summary,
        )
        cases_page = self._db.query_cases(
            suite["id"],
            limit=200,
            offset=0,
            include_details=False,
        )
        return {
            "project_id": proj.id,
            "env": target_env,
            "repo": target_env,
            "suite_id": suite["id"],
            "job_id": job_id,
            "exit_code": rc,
            "summary": summary,
            "cases": cases_page["cases"],
            "logs_tail": "\n".join(stdout_text.splitlines()[-60:]),
        }


UatService = EvalService
