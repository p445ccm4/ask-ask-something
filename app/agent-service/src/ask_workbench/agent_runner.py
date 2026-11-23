from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ag_workbench.approval_broker import ApprovalBroker
from ag_workbench.router import WorkbenchHooks, WorkspaceContext
from ag_workbench.runner import (
    AVAILABLE_MODELS,
    ActiveTurnRegistry,
    ConversationStore,
    ExecutionMode,
    build_capabilities,
    build_policies as _base_build_policies,
    is_destructive_command,
)

from .config import SKILLS_ROOT
from .uat_service import UatRunRequest, UatService
from .workspaces import WorkspaceEntry, WorkspaceRegistry, inspect_workspace_git

_ASK_READ_ONLY_TOOL_NAMES = {
    "get_uat_summary",
    "get_uat_case_detail",
    "get_git_diff",
}

_ASK_READ_ONLY_BLOCKED_TOOLS = {
    "run_uat_check",
}

_ASK_DESTRUCTIVE_REASON = (
    "Remote pushes (git push), destructive deletes (rm -rf), and cloud deployments are blocked for the AI agent. "
    "Use the Deploy buttons in the UI to push changes."
)

__all__ = [
    "AVAILABLE_MODELS",
    "ActiveTurnRegistry",
    "ApprovalBroker",
    "ConversationStore",
    "ExecutionMode",
    "build_capabilities",
    "build_host_tools",
    "build_policies",
    "build_system_instructions",
    "build_workbench_hooks",
    "is_destructive_command",
]


def build_policies(
    mode: ExecutionMode,
    conversation_id: str,
    approval_broker: ApprovalBroker,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]],
) -> list[Any]:
    return _base_build_policies(
        mode,
        conversation_id,
        approval_broker,
        emit_event,
        extra_read_only_tools=_ASK_READ_ONLY_TOOL_NAMES,
        read_only_blocked_tools=_ASK_READ_ONLY_BLOCKED_TOOLS,
        destructive_reason=_ASK_DESTRUCTIVE_REASON,
    )


def build_system_instructions(workspace: WorkspaceEntry | WorkspaceContext, mode: ExecutionMode) -> str:
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


def build_workbench_hooks(
    registry: WorkspaceRegistry,
    uat_service: UatService,
) -> WorkbenchHooks:
    def _resolve_ws(ws_id: str) -> WorkspaceContext:
        entry = registry.get_entry(ws_id)
        return WorkspaceContext(id=entry.id, name=entry.name, path=entry.path)

    def _build_tools(ws: WorkspaceContext, mode: ExecutionMode) -> list[Callable[..., Any]]:
        entry = registry.get_entry(ws.id)
        return build_host_tools(entry, uat_service, mode)

    def _on_mutated(ws: WorkspaceContext) -> dict[str, Any]:
        git_info = inspect_workspace_git(Path(ws.path))
        return {"type": "git_diff_updated", "git": git_info.model_dump()}

    return WorkbenchHooks(
        resolve_workspace=_resolve_ws,
        build_system_instructions=build_system_instructions,
        build_host_tools=_build_tools,
        extra_read_only_tool_names=set(_ASK_READ_ONLY_TOOL_NAMES),
        read_only_blocked_tools=set(_ASK_READ_ONLY_BLOCKED_TOOLS),
        skills_paths=[str(SKILLS_ROOT)] if SKILLS_ROOT.is_dir() else [],
        destructive_reason=_ASK_DESTRUCTIVE_REASON,
        on_turn_mutated=_on_mutated,
    )
