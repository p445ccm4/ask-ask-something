from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig
from google.antigravity.types import RunCommandConfig

from .agent_runner import (
    AVAILABLE_MODELS,
    ActiveTurnRegistry,
    ConversationStore,
    ExecutionMode,
    stream_agent_turn,
)
from .approval_broker import ApprovalBroker
from .config import Settings, get_settings
from .deploy_service import TargetEnv, execute_deploy, preview_deploy
from .uat_service import UatRunRequest, UatService
from .workspaces import WorkspaceRegistry, inspect_workspace_git


class AddWorkspaceRequest(BaseModel):
    name: str
    path: str
    uat_path: str | None = None
    env: str = "dev"


class CreateConversationRequest(BaseModel):
    workspace_id: str
    title: str = "New Investigation"


class ChatRequest(BaseModel):
    workspace_id: str
    message: str
    mode: ExecutionMode = "read_only"
    model: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approved: bool


class DeployExecuteRequest(BaseModel):
    target_env: TargetEnv
    commit_message: str
    selected_files: list[str] | None = None
    include_config_py: bool = False


def _sse_format(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
    conv_store = ConversationStore(cfg.conversations_file)
    turn_registry = ActiveTurnRegistry()

    app.state.settings = cfg
    app.state.registry = registry
    app.state.approval_broker = approval_broker
    app.state.uat_service = uat_service
    app.state.conv_store = conv_store
    app.state.turn_registry = turn_registry

    @app.get("/health")
    async def health(check_sandbox: bool = Query(default=False)) -> dict[str, Any]:
        sandbox_info: dict[str, Any] | None = None
        if check_sandbox:
            try:
                probe_cfg = LocalAgentConfig(
                    capabilities=CapabilitiesConfig(
                        run_command_config=RunCommandConfig(enable_sandbox=True)
                    ),
                    vertex=True,
                    project=cfg.resolved_vertex_project_id,
                    location=cfg.vertex_location,
                )
                async with Agent(probe_cfg) as agy:
                    st = agy.sandbox_status
                    sandbox_info = {
                        "available": bool(st.available) if st else False,
                        "unavailable_reason": getattr(st, "unavailable_reason", None),
                    }
            except Exception as exc:
                sandbox_info = {"available": False, "unavailable_reason": str(exc)}
        return {
            "status": "ok",
            "vertex_project_id": cfg.resolved_vertex_project_id or "",
            "vertex_location": cfg.vertex_location,
            "default_model": cfg.agent_model.strip() or "",
            "available_models": AVAILABLE_MODELS,
            "sandbox_status": sandbox_info,
        }

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
                yield _sse_format(ev)

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

    @app.get("/conversations")
    async def list_conversations(workspace_id: str | None = Query(default=None)) -> dict[str, Any]:
        items = conv_store.list_conversations(workspace_id=workspace_id)
        return {"conversations": [c.model_dump() for c in items]}

    @app.post("/conversations")
    async def create_conversation(req: CreateConversationRequest) -> dict[str, Any]:
        try:
            registry.get_entry(req.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rec = await conv_store.create(workspace_id=req.workspace_id, title=req.title)
        return {"conversation": rec.model_dump()}

    @app.get("/conversations/{conv_id}")
    async def get_conversation(conv_id: str) -> dict[str, Any]:
        try:
            rec = conv_store.get(conv_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"conversation": rec.model_dump()}

    @app.post("/conversations/{conv_id}/chat")
    async def chat_stream(conv_id: str, req: ChatRequest) -> StreamingResponse:
        try:
            entry = registry.get_entry(req.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        async def _gen():
            async for ev in stream_agent_turn(
                settings=cfg,
                workspace=entry,
                conversation_id=conv_id,
                user_message=req.message,
                mode=req.mode,
                model=req.model,
                approval_broker=approval_broker,
                uat_service=uat_service,
                conversation_store=conv_store,
                turn_registry=turn_registry,
            ):
                yield _sse_format(ev)

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.post("/conversations/{conv_id}/cancel")
    async def cancel_conversation_turn(conv_id: str) -> dict[str, Any]:
        cancelled_turn = await turn_registry.cancel(conv_id)
        cancelled_approvals = approval_broker.cancel_conversation(conv_id)
        return {
            "ok": True,
            "conversation_id": conv_id,
            "cancelled": bool(cancelled_turn or cancelled_approvals),
            "cancelled_approvals": cancelled_approvals,
        }

    @app.post("/approvals/{approval_id}")
    async def resolve_approval(approval_id: str, req: ApprovalDecisionRequest) -> dict[str, Any]:
        ok = approval_broker.resolve(approval_id, req.approved)
        if not ok:
            raise HTTPException(status_code=404, detail=f"No active pending approval: {approval_id}")
        return {"ok": True, "approval_id": approval_id, "approved": req.approved}

    return app


app = create_app()
