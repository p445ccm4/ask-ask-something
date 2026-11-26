from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ag_workbench.approval_broker import ApprovalBroker
from ag_workbench.attachments import AttachmentStore
from ag_workbench.auth import AuthLoginManager
from ag_workbench.router import create_workbench_router, sse_format
from ag_workbench.runner import (
    ActiveTurnRegistry,
    ConversationStore,
    WorkspaceLockRegistry,
    prune_old_sdk_sessions,
)
from ag_workbench.workspaces import browse_directories

from .agent_runner import build_workbench_hooks
from .ask_workbench_db import AskWorkbenchDB, EnvName
from .config import Settings, get_settings
from .deploy_service import (
    DeployMode,
    TargetEnv,
    compare_envs,
    execute_deploy,
    preview_deploy,
)
from .uat_service import EvalRunRequest, EvalService
from .workspaces import ProjectEntry, ProjectRegistry, inspect_workspace_git


class CreateProjectRequest(BaseModel):
    name: str
    environments: dict[str, str | None] = Field(default_factory=dict)
    active_env: EnvName | None = None
    # Optional convenience fields
    path: str | None = None
    uat_path: str | None = None
    env: EnvName | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    environments: dict[str, str | None] | None = None
    active_env: EnvName | None = None


class UpsertSuiteRequest(BaseModel):
    env: EnvName | None = None
    suite_id: str | None = None
    name: str
    slug: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    rubric_md: str | None = None
    excel_mapping: dict[str, Any] | None = None
    is_default: bool | None = None


class UpdateSuiteRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    rubric_md: str | None = None
    excel_mapping: dict[str, Any] | None = None
    is_default: bool | None = None


class UpsertCasesRequest(BaseModel):
    env: EnvName | None = None
    cases: list[dict[str, Any]] = Field(default_factory=list)
    replace_all: bool = False


class DeployExecuteRequest(BaseModel):
    target_env: TargetEnv
    source_env: TargetEnv | None = None
    commit_message: str
    selected_files: list[str] | None = None
    include_config_py: bool = False
    deploy_mode: DeployMode = "auto"
    force_overwrite: bool = False
    force_overwrite_uat: bool | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    app = FastAPI(title="AskAsk* Workbench API", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    db = AskWorkbenchDB(cfg.workbench_db_file)
    registry = ProjectRegistry(
        db,
        legacy_registry_file=cfg.workspaces_file,
        seed_defaults=True,
        default_workspaces_json=cfg.default_workspaces_json,
    )
    approval_broker = ApprovalBroker()
    eval_service = EvalService(
        db,
        templates_dir=cfg.templates_dir,
        exports_dir=cfg.exports_dir,
    )
    conv_store = ConversationStore(
        cfg.conversations_db_file,
        legacy_json_path=cfg.conversations_file,
    )
    turn_registry = ActiveTurnRegistry()
    workspace_locks = WorkspaceLockRegistry()
    attachment_store = AttachmentStore(
        cfg.attachments_dir,
        max_bytes=cfg.max_attachment_bytes,
    )
    auth_manager = AuthLoginManager()

    # Seed any legacy scripts/uat/ files read-only into SQLite on initial boot
    for proj in registry.list_entries():
        for env in proj.configured_envs:
            eval_service.ensure_env_seeded(proj, env)

    prune_old_sdk_sessions(
        cfg.sessions_dir,
        max_age_days=cfg.session_retention_days,
        max_sessions=cfg.max_retained_sessions,
    )
    attachment_store.prune_expired(max_age_days=cfg.attachment_retention_days)

    app.state.settings = cfg
    app.state.db = db
    app.state.registry = registry
    app.state.approval_broker = approval_broker
    app.state.eval_service = eval_service
    app.state.uat_service = eval_service
    app.state.conv_store = conv_store
    app.state.turn_registry = turn_registry
    app.state.workspace_locks = workspace_locks
    app.state.attachment_store = attachment_store
    app.state.auth_manager = auth_manager

    app.include_router(
        create_workbench_router(
            settings=cfg,
            hooks=build_workbench_hooks(registry, eval_service, settings=cfg),
            approval_broker=approval_broker,
            conv_store=conv_store,
            turn_registry=turn_registry,
            workspace_locks=workspace_locks,
            attachment_store=attachment_store,
            auth_manager=auth_manager,
        )
    )

    def _get_project_or_404(project_id: str) -> ProjectEntry:
        try:
            return registry.get_entry(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def _browse_folders_impl(
        path: str | None = None,
        include_hidden: bool = False,
    ) -> dict[str, Any]:
        registered = registry.all_registered_paths()
        try:
            return await asyncio.to_thread(
                browse_directories,
                path,
                include_hidden=include_hidden,
                registered_paths=registered,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Projects & Folder Browsing
    # ------------------------------------------------------------------
    @app.get("/workspaces/browse")
    async def browse_workspace_folders(
        path: str | None = Query(default=None),
        include_hidden: bool = Query(default=False),
    ) -> dict[str, Any]:
        return await _browse_folders_impl(path=path, include_hidden=include_hidden)

    @app.get("/projects/browse")
    async def browse_project_folders(
        path: str | None = Query(default=None),
        include_hidden: bool = Query(default=False),
    ) -> dict[str, Any]:
        return await _browse_folders_impl(path=path, include_hidden=include_hidden)

    @app.get("/projects")
    async def list_projects() -> dict[str, Any]:
        return {"projects": [p.model_dump() for p in registry.list_summaries()]}

    @app.post("/projects")
    async def create_project(req: CreateProjectRequest) -> dict[str, Any]:
        envs: dict[str, str | None] = dict(req.environments or {})
        if req.path and req.path.strip():
            envs.setdefault(req.env or req.active_env or "dev", req.path.strip())
        if req.uat_path and req.uat_path.strip():
            envs.setdefault("uat", req.uat_path.strip())
        try:
            entry = registry.add_project(
                name=req.name,
                environments=envs,
                active_env=req.active_env or req.env,
            )
            for env in entry.configured_envs:
                eval_service.ensure_env_seeded(entry, env)
            return {"project": registry.summarize(entry).model_dump()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        return {"project": registry.summarize(entry).model_dump()}

    @app.patch("/projects/{project_id}")
    async def update_project(project_id: str, req: UpdateProjectRequest) -> dict[str, Any]:
        _get_project_or_404(project_id)
        try:
            entry = registry.update_project(
                project_id,
                name=req.name,
                environments=req.environments,
                active_env=req.active_env,
            )
            for env in entry.configured_envs:
                eval_service.ensure_env_seeded(entry, env)
            return {"project": registry.summarize(entry).model_dump()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/projects/{project_id}")
    async def delete_project(project_id: str) -> dict[str, Any]:
        deleted = registry.delete_project(project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
        return {"ok": True, "deleted": True, "project_id": project_id}

    # ------------------------------------------------------------------
    # Git Diff, Environment Compare & Deploy / Promote
    # ------------------------------------------------------------------
    @app.get("/projects/{project_id}/git-diff")
    async def get_project_git_diff(
        project_id: str,
        env: EnvName | None = Query(default=None),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        target_env = env or entry.active_env
        try:
            path_str = entry.path_for_env(target_env)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        info = inspect_workspace_git(Path(path_str).expanduser())
        return {**info.model_dump(), "env": target_env}

    @app.get("/projects/{project_id}/compare")
    async def compare_project_envs(
        project_id: str,
        source_env: EnvName = Query(default="dev"),
        target_env: EnvName = Query(default="uat"),
        include_config_py: bool = Query(default=True),
        max_diff_chars: int = Query(default=20000, ge=1000, le=100000),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        res = compare_envs(
            entry,
            source_env=source_env,
            target_env=target_env,
            include_config_py=include_config_py,
            max_diff_chars=max_diff_chars,
        )
        if "error" in res:
            raise HTTPException(status_code=400, detail=res["error"])
        return res

    @app.get("/projects/{project_id}/deploy/preview")
    async def get_deploy_preview(
        project_id: str,
        target_env: TargetEnv = Query(...),
        source_env: TargetEnv | None = Query(default=None),
        include_config_py: bool = Query(default=False),
        deploy_mode: DeployMode = Query(default="auto"),
        force_overwrite: bool = Query(default=False),
        force_overwrite_uat: bool | None = Query(default=None),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        overwrite = force_overwrite_uat if force_overwrite_uat is not None else force_overwrite
        prev = preview_deploy(
            entry,
            target_env=target_env,
            include_config_py=include_config_py,
            deploy_mode=deploy_mode,
            force_overwrite=overwrite,
            source_env=source_env,
        )
        return prev.model_dump()

    @app.post("/projects/{project_id}/deploy/execute")
    async def run_deploy_execute(project_id: str, req: DeployExecuteRequest) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        overwrite = req.force_overwrite_uat if req.force_overwrite_uat is not None else req.force_overwrite
        try:
            res = execute_deploy(
                workspace=entry,
                target_env=req.target_env,
                commit_message=req.commit_message,
                selected_files=req.selected_files,
                include_config_py=req.include_config_py,
                deploy_mode=req.deploy_mode,
                force_overwrite=overwrite,
                source_env=req.source_env,
            )
            return res.model_dump()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Eval Suites, Cases, Excel Import/Export, Batch Run & Logs
    # ------------------------------------------------------------------
    @app.get("/projects/{project_id}/eval/overview")
    async def get_eval_overview(
        project_id: str,
        env: EnvName | None = Query(default=None),
        suite_id: str | None = Query(default=None),
        status: str = Query(default="ALL"),
        turn_filter: str = Query(default="ALL"),
        search: str = Query(default=""),
        sort_by: str = Query(default="ORDER"),
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            return eval_service.get_overview(
                entry,
                env=env,
                suite_id=suite_id,
                status=status,
                turn_filter=turn_filter,
                search=search,
                sort_by=sort_by,
                limit=limit,
                offset=offset,
                include_details=False,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/eval/suites")
    async def list_eval_suites(
        project_id: str,
        env: EnvName | None = Query(default=None),
        search: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            return eval_service.list_suites(entry, env=env, search=search, limit=limit, offset=offset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/eval/suites")
    async def create_or_update_eval_suite(
        project_id: str,
        req: UpsertSuiteRequest,
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            suite = eval_service.create_or_update_suite(
                entry,
                env=req.env,
                suite_id=req.suite_id,
                name=req.name,
                slug=req.slug,
                description=req.description,
                config=req.config,
                rubric_md=req.rubric_md,
                excel_mapping=req.excel_mapping,
                is_default=req.is_default,
            )
            return {"suite": suite}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/eval/suites/{suite_id}")
    async def get_eval_suite(project_id: str, suite_id: str) -> dict[str, Any]:
        _get_project_or_404(project_id)
        try:
            suite = db.get_suite(suite_id)
            if suite["project_id"] != project_id:
                raise HTTPException(status_code=404, detail=f"Eval suite '{suite_id}' not found in project.")
            return {
                "suite": suite,
                "summary": db.get_suite_summary(suite_id),
                "has_template_xlsx": (cfg.templates_dir / f"{suite_id}.xlsx").is_file(),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/projects/{project_id}/eval/suites/{suite_id}")
    async def patch_eval_suite(
        project_id: str,
        suite_id: str,
        req: UpdateSuiteRequest,
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            existing = db.get_suite(suite_id)
            if existing["project_id"] != project_id:
                raise HTTPException(status_code=404, detail=f"Eval suite '{suite_id}' not found in project.")
            suite = eval_service.create_or_update_suite(
                entry,
                env=existing["env"],
                suite_id=suite_id,
                name=req.name if req.name is not None else existing["name"],
                description=req.description,
                config=req.config,
                rubric_md=req.rubric_md,
                excel_mapping=req.excel_mapping,
                is_default=req.is_default,
            )
            return {"suite": suite}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/projects/{project_id}/eval/suites/{suite_id}")
    async def delete_eval_suite(project_id: str, suite_id: str) -> dict[str, Any]:
        _get_project_or_404(project_id)
        try:
            existing = db.get_suite(suite_id)
            if existing["project_id"] != project_id:
                raise HTTPException(status_code=404, detail=f"Eval suite '{suite_id}' not found in project.")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        deleted = eval_service.delete_suite(suite_id)
        return {"ok": True, "deleted": deleted, "suite_id": suite_id}

    @app.get("/projects/{project_id}/eval/suites/{suite_id}/cases")
    async def list_eval_cases(
        project_id: str,
        suite_id: str,
        env: EnvName | None = Query(default=None),
        status: str = Query(default="ALL"),
        turn_filter: str = Query(default="ALL"),
        search: str = Query(default=""),
        sort_by: str = Query(default="ORDER"),
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        include_details: bool = Query(default=False),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            target_env = env or db.get_suite(suite_id)["env"]
            return eval_service.query_cases(
                entry,
                env=target_env,
                suite_id=suite_id,
                status=status,
                turn_filter=turn_filter,
                search=search,
                sort_by=sort_by,
                limit=limit,
                offset=offset,
                include_details=include_details,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/eval/suites/{suite_id}/cases")
    async def upsert_eval_cases(
        project_id: str,
        suite_id: str,
        req: UpsertCasesRequest,
    ) -> dict[str, Any]:
        _get_project_or_404(project_id)
        try:
            existing = db.get_suite(suite_id)
            if existing["project_id"] != project_id:
                raise HTTPException(status_code=404, detail=f"Eval suite '{suite_id}' not found in project.")
            cnt = eval_service.upsert_cases(
                suite_id, req.cases, replace_all=req.replace_all
            )
            return {
                "ok": True,
                "upserted_count": cnt,
                "summary": db.get_suite_summary(suite_id),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/eval/suites/{suite_id}/cases/{case_id}")
    async def get_eval_case_detail_endpoint(
        project_id: str,
        suite_id: str,
        case_id: str,
        env: EnvName | None = Query(default=None),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            target_env = env or db.get_suite(suite_id)["env"]
            return eval_service.get_case_detail(
                entry, case_id, env=target_env, suite_id=suite_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/projects/{project_id}/eval/suites/{suite_id}/cases/{case_id}")
    async def delete_eval_case(
        project_id: str,
        suite_id: str,
        case_id: str,
    ) -> dict[str, Any]:
        _get_project_or_404(project_id)
        try:
            existing = db.get_suite(suite_id)
            if existing["project_id"] != project_id:
                raise HTTPException(status_code=404, detail=f"Eval suite '{suite_id}' not found in project.")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        deleted = eval_service.delete_case(suite_id, case_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Eval case '{case_id}' not found.")
        return {"ok": True, "deleted": True, "summary": db.get_suite_summary(suite_id)}

    @app.post("/projects/{project_id}/eval/inspect-xlsx")
    async def inspect_xlsx_upload(
        project_id: str,
        file: UploadFile = File(...),
        sheet: str | None = Form(default=None),
    ) -> dict[str, Any]:
        _get_project_or_404(project_id)
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded Excel file is empty.")
        try:
            return eval_service.inspect_xlsx_bytes(
                content, file.filename or "upload.xlsx", sheet_name=sheet
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/eval/import-xlsx")
    async def import_xlsx_upload(
        project_id: str,
        file: UploadFile = File(...),
        env: EnvName | None = Form(default=None),
        suite_name: str | None = Form(default=None),
        suite_id: str | None = Form(default=None),
        mapping_json: str | None = Form(default=None),
        config_json: str | None = Form(default=None),
        rubric_md: str | None = Form(default=None),
        replace_all: bool = Form(default=True),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded Excel file is empty.")
        try:
            mapping = json.loads(mapping_json) if mapping_json and mapping_json.strip() else None
            config_obj = json.loads(config_json) if config_json and config_json.strip() else None
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON field: {exc}") from exc

        try:
            return eval_service.import_xlsx_bytes(
                entry,
                env=env,
                content=content,
                filename=file.filename or "eval_suite.xlsx",
                suite_name=suite_name,
                suite_id=suite_id,
                mapping=mapping,
                config=config_obj,
                rubric_md=rubric_md,
                replace_all=replace_all,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/eval/import-legacy")
    async def import_legacy_eval(
        project_id: str,
        env: EnvName | None = Query(default=None),
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            return eval_service.import_legacy_from_repo(
                entry, env=env, only_if_empty=not force
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/eval/run")
    async def start_eval_run(project_id: str, req: EvalRunRequest) -> dict[str, Any]:
        entry = _get_project_or_404(project_id)
        try:
            job = await eval_service.start_run_job(entry, req)
            return {
                "job_id": job.job_id,
                "suite_id": job.suite_id,
                "env": job.env,
                "command": job.command,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/eval/jobs/{job_id}/stream")
    async def stream_eval_job(job_id: str) -> StreamingResponse:
        try:
            eval_service.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        async def _gen():
            async for ev in eval_service.stream_job(job_id):
                yield sse_format(ev)

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/eval/jobs/{job_id}")
    async def get_eval_job_logs(job_id: str) -> dict[str, Any]:
        try:
            return eval_service.get_run_logs(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/eval/suites/{suite_id}/runs")
    async def list_eval_suite_runs(
        project_id: str,
        suite_id: str,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        _get_project_or_404(project_id)
        try:
            suite = db.get_suite(suite_id)
            if suite["project_id"] != project_id:
                raise HTTPException(status_code=404, detail=f"Eval suite '{suite_id}' not found in project.")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"runs": db.list_runs(suite_id, limit=limit)}

    @app.get("/projects/{project_id}/eval/suites/{suite_id}/export-csv")
    async def export_eval_csv(
        project_id: str,
        suite_id: str,
        env: EnvName | None = Query(default=None),
    ) -> FileResponse:
        entry = _get_project_or_404(project_id)
        try:
            target_env = env or db.get_suite(suite_id)["env"]
            csv_path = eval_service.export_csv(entry, env=target_env, suite_id=suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path=csv_path,
            filename=f"{suite_id}_eval_results.csv",
            media_type="text/csv; charset=utf-8",
        )

    @app.get("/projects/{project_id}/eval/suites/{suite_id}/export-xlsx")
    async def export_eval_xlsx(
        project_id: str,
        suite_id: str,
        env: EnvName | None = Query(default=None),
    ) -> FileResponse:
        entry = _get_project_or_404(project_id)
        try:
            target_env = env or db.get_suite(suite_id)["env"]
            xlsx_path = eval_service.export_xlsx(entry, env=target_env, suite_id=suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path=xlsx_path,
            filename=f"{suite_id}_eval_updated.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return app


app = create_app()
