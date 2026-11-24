from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ag_workbench.approval_broker import ApprovalBroker
from ag_workbench.auth import AuthLoginManager
from ag_workbench.router import create_workbench_router, sse_format
from ag_workbench.runner import (
    ActiveTurnRegistry,
    ConversationStore,
    WorkspaceLockRegistry,
    prune_old_sdk_sessions,
)

from .agent_runner import build_workbench_hooks
from .config import Settings, get_settings
from .deploy_service import TargetEnv, execute_deploy, preview_deploy
from .uat_service import UatRunRequest, UatService
from .workspaces import WorkspaceRegistry, inspect_workspace_git


class AddWorkspaceRequest(BaseModel):
    name: str
    path: str
    uat_path: str | None = None
    env: str = "dev"


class DeployExecuteRequest(BaseModel):
    target_env: TargetEnv
    commit_message: str
    selected_files: list[str] | None = None
    include_config_py: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    app = FastAPI(title="AskAsk* Workbench API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    registry = WorkspaceRegistry(
        cfg.workspaces_file,
        seed_defaults=True,
        default_workspaces_json=cfg.default_workspaces_json,
    )
    approval_broker = ApprovalBroker()
    uat_service = UatService()
    conv_store = ConversationStore(
        cfg.conversations_db_file,
        legacy_json_path=cfg.conversations_file,
    )
    turn_registry = ActiveTurnRegistry()
    workspace_locks = WorkspaceLockRegistry()
    auth_manager = AuthLoginManager()

    prune_old_sdk_sessions(
        cfg.sessions_dir,
        max_age_days=cfg.session_retention_days,
        max_sessions=cfg.max_retained_sessions,
    )

    app.state.settings = cfg
    app.state.registry = registry
    app.state.approval_broker = approval_broker
    app.state.uat_service = uat_service
    app.state.conv_store = conv_store
    app.state.turn_registry = turn_registry
    app.state.workspace_locks = workspace_locks
    app.state.auth_manager = auth_manager

    app.include_router(
        create_workbench_router(
            settings=cfg,
            hooks=build_workbench_hooks(registry, uat_service, settings=cfg),
            approval_broker=approval_broker,
            conv_store=conv_store,
            turn_registry=turn_registry,
            workspace_locks=workspace_locks,
            auth_manager=auth_manager,
        )
    )

    @app.get("/workspaces")
    async def list_workspaces() -> dict[str, Any]:
        return {"workspaces": [w.model_dump() for w in registry.list_summaries()]}

    @app.post("/workspaces")
    async def add_workspace(req: AddWorkspaceRequest) -> dict[str, Any]:
        try:
            entry = registry.add_entry(
                name=req.name,
                path=req.path,
                uat_path=req.uat_path,
                env=req.env,
            )
            return {"workspace": registry.summarize(entry).model_dump()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/workspaces/{ws_id}/git-diff")
    async def get_workspace_git_diff(ws_id: str) -> dict[str, Any]:
        try:
            entry = registry.get_entry(ws_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        info = inspect_workspace_git(Path(entry.path))
        return info.model_dump()

    @app.get("/workspaces/{ws_id}/deploy/preview")
    async def get_deploy_preview(
        ws_id: str,
        target_env: Literal["dev", "uat"] = Query(...),
        include_config_py: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            entry = registry.get_entry(ws_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        prev = preview_deploy(entry, target_env=target_env, include_config_py=include_config_py)
        return prev.model_dump()

    @app.post("/workspaces/{ws_id}/deploy/execute")
    async def run_deploy_execute(ws_id: str, req: DeployExecuteRequest) -> dict[str, Any]:
        try:
            entry = registry.get_entry(ws_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            res = execute_deploy(
                workspace=entry,
                target_env=req.target_env,
                commit_message=req.commit_message,
                selected_files=req.selected_files,
                include_config_py=req.include_config_py,
            )
            return res.model_dump()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/workspaces/{ws_id}/uat/overview")
    async def get_uat_overview(ws_id: str) -> dict[str, Any]:
        try:
            entry = registry.get_entry(ws_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return uat_service.get_overview(entry).model_dump()

    @app.post("/workspaces/{ws_id}/uat/run")
    async def start_uat_run(ws_id: str, req: UatRunRequest) -> dict[str, Any]:
        try:
            entry = registry.get_entry(ws_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            job = await uat_service.start_run_job(entry, req)
            return {"job_id": job.job_id, "command": job.command}
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/uat/jobs/{job_id}/stream")
    async def stream_uat_job(job_id: str) -> StreamingResponse:
        try:
            uat_service.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        async def _gen():
            async for ev in uat_service.stream_job(job_id):
                yield sse_format(ev)

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/workspaces/{ws_id}/uat/export-csv")
    async def export_uat_csv(ws_id: str) -> FileResponse:
        try:
            entry = registry.get_entry(ws_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            csv_path = await uat_service.export_csv(entry)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path=csv_path,
            filename=f"{ws_id}_uat_results.csv",
            media_type="text/csv; charset=utf-8",
        )

    return app


app = create_app()
