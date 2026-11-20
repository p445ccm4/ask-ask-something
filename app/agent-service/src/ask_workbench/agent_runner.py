from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig, models as ag_models, types
from google.antigravity.hooks import policy
from google.antigravity.types import BuiltinTools, RunCommandConfig, SessionContinuationMode, ToolCall

from .approval_broker import ApprovalBroker
from .config import SKILLS_ROOT, Settings
from .uat_service import UatRunRequest, UatService
from .workspaces import WorkspaceEntry, inspect_workspace_git

ExecutionMode = Literal["read_only", "ask_before_fix", "sandboxed_auto"]

AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "", "label": f"Auto ({ag_models.DEFAULT_MODEL})"},
    {"id": "gemini-4-hydrogen", "label": "Gemini 4 Hydrogen"},
    {"id": "gemini-4-argon", "label": "Gemini 4 Argon"},
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
]

_DESTRUCTIVE_CMD_PATTERNS = (
    re.compile(r"\bgit\s+push\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+/", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f|\brm\s+-[a-zA-Z]*f[a-zA-Z]*r", re.IGNORECASE),
    re.compile(r"\bgcloud\s+.*\b(deploy|delete|destroy)\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b|\breboot\b|\bmkfs\b", re.IGNORECASE),
)

_READ_ONLY_BUILTIN_TOOLS = [
    BuiltinTools.VIEW_FILE,
    BuiltinTools.LIST_DIR,
    BuiltinTools.SEARCH_DIR,
    BuiltinTools.FIND_FILE,
    BuiltinTools.FINISH,
]

_WRITE_AND_EXEC_BUILTIN_TOOLS = [
    BuiltinTools.VIEW_FILE,
    BuiltinTools.LIST_DIR,
    BuiltinTools.SEARCH_DIR,
    BuiltinTools.FIND_FILE,
    BuiltinTools.EDIT_FILE,
    BuiltinTools.CREATE_FILE,
    BuiltinTools.RUN_COMMAND,
    BuiltinTools.FINISH,
]

_READ_ONLY_TOOL_NAMES = {
    "view_file",
    "list_directory",
    "search_directory",
    "find_file",
    "finish",
    "get_uat_summary",
    "get_uat_case_detail",
    "get_git_diff",
}


class ConversationRecord(BaseModel):
    conversation_id: str
    workspace_id: str
    title: str
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    messages: list[dict[str, Any]] = Field(default_factory=list)


class ConversationStore:
    def __init__(self, file_path: Path) -> None:
        self._file = file_path
        self._lock = asyncio.Lock()

    def _read_all(self) -> list[ConversationRecord]:
        if not self._file.is_file():
            return []
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        return [ConversationRecord.model_validate(item) for item in raw]

    def _write_all(self, records: list[ConversationRecord]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps([r.model_dump() for r in records], indent=2),
            encoding="utf-8",
        )

    def list_conversations(self, workspace_id: str | None = None) -> list[ConversationRecord]:
        items = self._read_all()
        if workspace_id:
            items = [i for i in items if i.workspace_id == workspace_id]
        return sorted(items, key=lambda r: r.updated_at, reverse=True)

    def get(self, conversation_id: str) -> ConversationRecord:
        for item in self._read_all():
            if item.conversation_id == conversation_id:
                return item
        raise KeyError(f"Conversation not found: {conversation_id}")

    async def create(self, workspace_id: str, title: str = "New Investigation") -> ConversationRecord:
        async with self._lock:
            items = self._read_all()
            rec = ConversationRecord(
                conversation_id=str(uuid4()),
                workspace_id=workspace_id,
                title=title.strip() or "New Investigation",
            )
            items.append(rec)
            self._write_all(items)
            return rec

    async def append_turn(
        self,
        conversation_id: str,
        workspace_id: str,
        user_message: str,
        assistant_payload: dict[str, Any],
    ) -> ConversationRecord:
        async with self._lock:
            items = self._read_all()
            target = next((i for i in items if i.conversation_id == conversation_id), None)
            if target is None:
                target = ConversationRecord(
                    conversation_id=conversation_id,
                    workspace_id=workspace_id,
                    title=user_message.strip()[:60] or "Investigation",
                )
                items.append(target)
            elif target.title in {"New Investigation", ""} and user_message.strip():
                target.title = user_message.strip().splitlines()[0][:70]

            target.messages.append(
                {
                    "role": "user",
                    "content": user_message,
                    "timestamp": time.time(),
                }
            )
            target.messages.append(
                {
                    "role": "assistant",
                    "timestamp": time.time(),
                    **assistant_payload,
                }
            )
            target.updated_at = time.time()
            self._write_all(items)
            return target


def is_destructive_command(args: dict[str, Any]) -> bool:
    cmd = str(args.get("command_line") or args.get("CommandLine") or "")
    return any(pattern.search(cmd) for pattern in _DESTRUCTIVE_CMD_PATTERNS)


def build_capabilities(mode: ExecutionMode) -> CapabilitiesConfig:
    if mode == "read_only":
        return CapabilitiesConfig(
            enable_subagents=False,
            enabled_tools=list(_READ_ONLY_BUILTIN_TOOLS),
        )
    return CapabilitiesConfig(
        enable_subagents=False,
        enabled_tools=list(_WRITE_AND_EXEC_BUILTIN_TOOLS),
        run_command_config=RunCommandConfig(
            enable_sandbox=True,
            timeout_seconds=180.0,
        ),
    )


def build_policies(
    mode: ExecutionMode,
    conversation_id: str,
    approval_broker: ApprovalBroker,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]],
) -> list[Any]:
    safety_blocks = [
        policy.deny(
            "run_command",
            when=is_destructive_command,
            name="block_destructive_or_push_commands",
            reason="Remote pushes (git push), destructive deletes (rm -rf), and cloud deployments are blocked for the AI agent. Use the Deploy buttons in the UI to push changes.",
        )
    ]

    if mode == "read_only":
        return [
            *safety_blocks,
            policy.deny("edit_file", name="read_only_deny_edit", reason="Read-Only Inspect mode is active."),
            policy.deny("create_file", name="read_only_deny_create", reason="Read-Only Inspect mode is active."),
            policy.deny("run_command", name="read_only_deny_cmd", reason="Read-Only Inspect mode is active."),
            policy.deny("run_uat_check", name="read_only_deny_uat_run", reason="Read-Only Inspect mode is active."),
            policy.allow("*"),
        ]

    if mode == "ask_before_fix":
        async def _ask_handler(tool_call: ToolCall) -> bool:
            return await approval_broker.request_approval(
                conversation_id=conversation_id,
                tool_name=tool_call.name,
                args=dict(tool_call.args or {}),
                emit_event=emit_event,
            )

        return [
            *safety_blocks,
            *[policy.allow(name) for name in sorted(_READ_ONLY_TOOL_NAMES)],
            policy.ask_user("edit_file", handler=_ask_handler, name="hitl_edit_file"),
            policy.ask_user("create_file", handler=_ask_handler, name="hitl_create_file"),
            policy.ask_user("run_command", handler=_ask_handler, name="hitl_run_command"),
            policy.ask_user("run_uat_check", handler=_ask_handler, name="hitl_run_uat_check"),
            policy.ask_user("*", handler=_ask_handler, name="hitl_fallback"),
        ]

    # sandboxed_auto
    return [
        *safety_blocks,
        policy.allow("*"),
    ]


def build_system_instructions(workspace: WorkspaceEntry, mode: ExecutionMode) -> str:
    mode_note = {
        "read_only": (
            "CURRENT EXECUTION MODE: READ-ONLY INSPECT. "
            "You can inspect files, git diffs, and UAT results/logs, but you MUST NOT attempt edits or shell commands. "
            "Provide concrete root-cause analysis and exact proposed file/line fixes."
        ),
        "ask_before_fix": (
            "CURRENT EXECUTION MODE: ASK-BEFORE-FIX (Human-in-the-Loop). "
            "Read/search tools run automatically, while edits, shell commands, and UAT runs pause for user approval in the UI."
        ),
        "sandboxed_auto": (
            "CURRENT EXECUTION MODE: SANDBOXED AUTO-FIX. "
            "You may edit files inside the workspace and run local tests inside the Linux sandbox. "
            "`git push` and destructive commands remain blocked — the human user pushes via the UI Deploy buttons."
        ),
    }[mode]

    return (
        f"You are the AskAsk* Maintainer Agent for workspace '{workspace.name}' located at '{workspace.path}'.\n"
        f"{mode_note}\n\n"
        "ARCHITECTURE & TOOL BOUNDARIES:\n"
        "- Built-in file tools (`view_file`, `search_directory`, `find_file`, `list_directory`, `edit_file`, `create_file`) "
        "and `run_command` are strictly scoped to the target service workspace.\n"
        "- To inspect UAT results, read case details, or execute HTTP UAT batch runs (including Cloud Run gcloud auth & LLM-as-a-Judge), "
        "ALWAYS use the host tools `get_uat_summary`, `get_uat_case_detail`, and `run_uat_check` instead of invoking `run_uat_batch.py` inside `run_command`.\n"
        "- Follow the `ask-ask-something` debugging discipline: inspect actual vs expected answer/behavior & retrieved sources -> "
        "inspect prompts/RAG/service code -> make targeted fixes -> verify with targeted `run_uat_check(case_ids=...)` and `runs=5` stability check -> "
        "remind/run full regression (`run_uat_check(case_ids='')`).\n"
        "- NEVER attempt `git push`. When fixes are verified, summarize the git diff and tell the user they can click Deploy to DEV / Deploy to UAT."
    )


def build_host_tools(
    workspace: WorkspaceEntry,
    uat_service: UatService,
    mode: ExecutionMode,
) -> list[Callable[..., Any]]:
    async def get_uat_summary() -> dict[str, Any]:
        """Return overall UAT evaluation score and FAIL/PARTIAL case IDs for the active workspace."""
        overview = uat_service.get_overview(workspace)
        flagged = []
        for item in overview.results:
            rev = item.get("uat_review") or {}
            status = str(rev.get("status") or "").upper()
            if status in {"FAIL", "PARTIAL"}:
                flagged.append(
                    {
                        "id": item.get("id"),
                        "status": status,
                        "score": rev.get("score"),
                        "comment": rev.get("comment"),
                    }
                )
        return {
            "workspace": workspace.name,
            "has_config": overview.has_config,
            "has_questions": overview.has_questions,
            "has_results": overview.has_results,
            "summary": overview.summary.model_dump(),
            "flagged_cases": flagged,
            "rubric_preview": overview.rubric_preview[:3000],
        }

    async def get_uat_case_detail(case_id: str) -> dict[str, Any]:
        """Fetch full turn questions, expected answers/behaviors, actual answers, retrieved sources, and judge reviews for a UAT case ID (e.g. 'Q4')."""
        return uat_service.get_case_detail(workspace, case_id)

    async def get_git_diff() -> dict[str, Any]:
        """Inspect the current branch, modified files, and unified git diff scoped to the active service workspace."""
        info = inspect_workspace_git(Path(workspace.path))
        return info.model_dump()

    async def run_uat_check(
        case_ids: str = "",
        turn: int | None = None,
        runs: int = 1,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Run UAT batch evaluation against the configured target endpoint. Pass comma-separated case_ids (e.g. 'Q4') for targeted debugging, or leave empty for full regression."""
        req = UatRunRequest(case_ids=case_ids, turn=turn, runs=runs, limit=limit)
        return await uat_service.run_and_collect(workspace, req)

    tools: list[Callable[..., Any]] = [get_uat_summary, get_uat_case_detail, get_git_diff]
    if mode != "read_only":
        tools.append(run_uat_check)
    return tools


@dataclass
class ActiveTurn:
    conversation_id: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    response: types.ChatResponse | None = None
    worker: asyncio.Task[None] | None = None


class ActiveTurnRegistry:
    """Tracks active streaming agent turns so the UI can cancel/stop mid-generation."""

    def __init__(self) -> None:
        self._turns: dict[str, ActiveTurn] = {}

    def register(self, turn: ActiveTurn) -> None:
        self._turns[turn.conversation_id] = turn

    def unregister(self, conversation_id: str, turn: ActiveTurn) -> None:
        if self._turns.get(conversation_id) is turn:
            self._turns.pop(conversation_id, None)

    def get(self, conversation_id: str) -> ActiveTurn | None:
        return self._turns.get(conversation_id)

    async def cancel(self, conversation_id: str) -> bool:
        turn = self._turns.get(conversation_id)
        if turn is None:
            return False
        turn.cancel_event.set()
        if turn.response is not None:
            try:
                await turn.response.cancel()
            except Exception:
                pass
        elif turn.worker is not None and not turn.worker.done():
            turn.worker.cancel()
        return True


async def stream_agent_turn(
    *,
    settings: Settings,
    workspace: WorkspaceEntry,
    conversation_id: str,
    user_message: str,
    mode: ExecutionMode,
    model: str | None = None,
    approval_broker: ApprovalBroker,
    uat_service: UatService,
    conversation_store: ConversationStore,
    turn_registry: ActiveTurnRegistry | None = None,
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(ev: dict[str, Any]) -> None:
        await queue.put(ev)

    if turn_registry is not None and turn_registry.get(conversation_id) is not None:
        await turn_registry.cancel(conversation_id)
        approval_broker.cancel_conversation(conversation_id)

    turn = ActiveTurn(conversation_id=conversation_id)
    if turn_registry is not None:
        turn_registry.register(turn)

    tools = build_host_tools(workspace, uat_service, mode)
    capabilities = build_capabilities(mode)
    policies = build_policies(mode, conversation_id, approval_broker, emit)
    skills_paths = [str(SKILLS_ROOT)] if SKILLS_ROOT.is_dir() else []

    chosen_model = (model or "").strip() or settings.agent_model.strip()

    config_kwargs: dict[str, Any] = {
        "system_instructions": build_system_instructions(workspace, mode),
        "workspaces": [str(Path(workspace.path).resolve())],
        "skills_paths": skills_paths,
        "tools": tools,
        "capabilities": capabilities,
        "policies": policies,
        "conversation_id": conversation_id,
        "session_continuation_mode": SessionContinuationMode.CREATE_OR_RESUME,
        "save_dir": str(settings.sessions_dir),
        "vertex": True,
        "project": settings.resolved_vertex_project_id,
        "location": settings.vertex_location,
    }
    if chosen_model:
        config_kwargs["model"] = chosen_model

    config = LocalAgentConfig(**config_kwargs)

    async def _run_worker() -> None:
        thoughts_parts: list[str] = []
        text_parts: list[str] = []
        tool_events: list[dict[str, Any]] = []
        mutated = False
        cancelled_by_user = False

        try:
            if not turn.cancel_event.is_set():
                async with Agent(config) as agent:
                    response = await agent.chat(user_message)
                    turn.response = response
                    if turn.cancel_event.is_set():
                        cancelled_by_user = True
                        try:
                            await response.cancel()
                        except Exception:
                            pass
                    else:
                        async for chunk in response.chunks:
                            if turn.cancel_event.is_set():
                                cancelled_by_user = True
                                try:
                                    await response.cancel()
                                except Exception:
                                    pass
                                break
                            if isinstance(chunk, types.Thought):
                                if chunk.text:
                                    thoughts_parts.append(chunk.text)
                                    await emit({"type": "thought", "delta": chunk.text})
                            elif isinstance(chunk, types.Text):
                                if chunk.text:
                                    text_parts.append(chunk.text)
                                    await emit({"type": "text", "delta": chunk.text})
                            elif isinstance(chunk, types.ToolCall):
                                if chunk.name in {"edit_file", "create_file", "run_command"}:
                                    mutated = True
                                ev = {
                                    "type": "tool_call",
                                    "id": chunk.id,
                                    "name": chunk.name,
                                    "args": chunk.args,
                                }
                                tool_events.append(ev)
                                await emit(ev)
                            elif isinstance(chunk, types.ToolResult):
                                res_text = chunk.result
                                if not isinstance(res_text, str):
                                    try:
                                        res_text = json.dumps(res_text, ensure_ascii=False, indent=2)
                                    except TypeError:
                                        res_text = str(res_text)
                                ev = {
                                    "type": "tool_result",
                                    "id": chunk.id,
                                    "name": chunk.name,
                                    "result": res_text[:8000] if res_text else "",
                                    "error": chunk.error,
                                }
                                tool_events.append(ev)
                                await emit(ev)
            else:
                cancelled_by_user = True
        except asyncio.CancelledError:
            cancelled_by_user = True
        except Exception as exc:
            if turn.cancel_event.is_set():
                cancelled_by_user = True
            else:
                await emit({"type": "error", "message": str(exc)})
                return
        finally:
            if turn_registry is not None:
                turn_registry.unregister(conversation_id, turn)
            if turn.cancel_event.is_set():
                cancelled_by_user = True

        full_text = "".join(text_parts)
        full_thought = "".join(thoughts_parts)
        try:
            await conversation_store.append_turn(
                conversation_id=conversation_id,
                workspace_id=workspace.id,
                user_message=user_message,
                assistant_payload={
                    "content": full_text,
                    "thought": full_thought,
                    "tool_events": tool_events,
                    "mode": mode,
                    "model": chosen_model or ag_models.DEFAULT_MODEL,
                    "cancelled": cancelled_by_user,
                },
            )
        except Exception:
            pass

        if mutated:
            git_info = inspect_workspace_git(Path(workspace.path))
            await emit({"type": "git_diff_updated", "git": git_info.model_dump()})

        await emit(
            {
                "type": "done",
                "conversation_id": conversation_id,
                "content": full_text,
                "mutated": mutated,
                "cancelled": cancelled_by_user,
            }
        )

    async def _worker_wrapper() -> None:
        try:
            await _run_worker()
        finally:
            await queue.put(None)

    worker = asyncio.create_task(_worker_wrapper())
    turn.worker = worker
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if not worker.done():
            turn.cancel_event.set()
            approval_broker.cancel_conversation(conversation_id)
            if turn.response is not None:
                try:
                    await turn.response.cancel()
                except Exception:
                    pass
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass
        if turn_registry is not None:
            turn_registry.unregister(conversation_id, turn)
