from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import ag_workbench
from ag_workbench.approval_broker import ApprovalBroker
from ag_workbench.artifacts import AG_ARTIFACTS_DIR_NAME
from ag_workbench.commands import default_user_skills_paths, merge_skills_paths
from ag_workbench.config import WorkbenchSettings
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
from .deploy_service import compare_dev_and_uat as _compare_dev_and_uat
from .uat_service import UatRunRequest, UatService
from .workspaces import WorkspaceEntry, WorkspaceRegistry, inspect_workspace_git

_BUILTIN_WORKBENCH_SKILLS_DIR = Path(ag_workbench.__file__).resolve().parent / "skills"

_ASK_READ_ONLY_TOOL_NAMES = {
    "get_uat_summary",
    "get_uat_case_detail",
    "get_git_diff",
    "compare_dev_and_uat",
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


def _resolve_uat_path(workspace: WorkspaceEntry | WorkspaceContext) -> str | None:
    uat_path = getattr(workspace, "uat_path", None)
    if isinstance(uat_path, str) and uat_path.strip():
        return uat_path.strip()
    extra_paths = getattr(workspace, "extra_paths", None) or ()
    for candidate in extra_paths:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


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
        "unsandboxed_auto": (
            "CURRENT EXECUTION MODE: UNSANDBOXED AUTO-FIX. "
            "You may edit files inside the workspace and run shell commands directly on the host without the Linux sandbox or destructive-command blocks. "
            "Still let the human user push changes via the UI Deploy buttons."
        ),
    }[mode]

    uat_path = _resolve_uat_path(workspace)
    uat_section = ""
    if uat_path:
        uat_section = (
            f"\nPAIRED UAT REPOSITORY (EDITABLE MULTI-WORKSPACE):\n"
            f"- Primary DEV repository path: '{workspace.path}'\n"
            f"- Paired UAT repository path: '{uat_path}'\n"
            "- Both the primary DEV repository and the paired UAT repository are mounted as editable workspaces for built-in file tools (`view_file`, `search_directory`, `find_file`, `list_directory`, `edit_file`, `create_file`) and `run_command`.\n"
            f"- Always pass explicit/absolute paths under '{uat_path}' when inspecting or editing UAT files (relative paths default to the primary DEV workspace), and verify `Cwd` when running shell commands.\n"
            "- Use `compare_dev_and_uat` to diff code/config between DEV and UAT, and pass `repo='uat'` to `get_uat_summary`, `get_uat_case_detail`, `get_git_diff`, or `run_uat_check` when targeting the UAT repository.\n"
            "- Remember that `src/config.py` holds environment-specific `PROJECT_ID` / bucket configuration; do not overwrite UAT `src/config.py` unless explicitly requested.\n"
        )

    return (
        f"You are the AskAsk* Maintainer Agent for workspace '{workspace.name}' located at '{workspace.path}'.\n"
        f"{mode_note}\n"
        f"{uat_section}\n"
        "ARCHITECTURE & TOOL BOUNDARIES:\n"
        "- Built-in file tools (`view_file`, `search_directory`, `find_file`, `list_directory`, `edit_file`, `create_file`) "
        "and `run_command` are strictly scoped to the configured target workspace root(s).\n"
        "- Use `attach_output_file(file_path, caption)` to deliver any workspace file, report, or image directly to the user in the chatbox.\n"
        f"- For interactive HTML widgets/mockups, follow the `generative_ui` skill (save self-contained `.html` files under `{AG_ARTIFACTS_DIR_NAME}/` and embed compact widgets via `<agent-embed src=\"{AG_ARTIFACTS_DIR_NAME}/widget.html\"></agent-embed>` or link larger dashboards with standard markdown links).\n"
        "- When `search_web` is enabled, use it to look up up-to-date external documentation, releases, or references when needed.\n"
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
    async def get_uat_summary(repo: Literal["dev", "uat"] = "dev") -> dict[str, Any]:
        """Return overall UAT evaluation score and FAIL/PARTIAL case IDs for the active workspace (or paired 'uat' repo)."""
        try:
            overview = uat_service.get_overview(workspace, repo=repo)
        except (ValueError, FileNotFoundError) as exc:
            return {"error": str(exc), "repo": repo}
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
            "repo": repo,
            "has_config": overview.has_config,
            "has_questions": overview.has_questions,
            "has_results": overview.has_results,
            "summary": overview.summary.model_dump(),
            "flagged_cases": flagged,
            "rubric_preview": overview.rubric_preview[:3000],
        }

    async def get_uat_case_detail(case_id: str, repo: Literal["dev", "uat"] = "dev") -> dict[str, Any]:
        """Fetch full turn questions, expected answers/behaviors, actual answers, retrieved sources, and judge reviews for a UAT case ID (e.g. 'Q4') from 'dev' or 'uat'."""
        try:
            return uat_service.get_case_detail(workspace, case_id, repo=repo)
        except (ValueError, FileNotFoundError, KeyError) as exc:
            return {"error": str(exc), "repo": repo, "case_id": case_id}

    async def get_git_diff(repo: Literal["dev", "uat"] = "dev") -> dict[str, Any]:
        """Inspect the current branch, modified files, and unified git diff scoped to the active 'dev' or paired 'uat' service directory."""
        if repo == "uat":
            raw_uat = (workspace.uat_path or "").strip()
            if not raw_uat:
                return {"error": f"No paired UAT repository is configured for workspace '{workspace.name}'.", "repo": "uat"}
            target = Path(raw_uat).expanduser()
        else:
            target = Path(workspace.path)
        info = inspect_workspace_git(target)
        return {**info.model_dump(), "repo": repo}

    async def compare_dev_and_uat(
        include_config_py: bool = True,
        max_diff_chars: int = 20000,
    ) -> dict[str, Any]:
        """Compare files and unified diffs between the DEV workspace and its paired UAT repository."""
        return _compare_dev_and_uat(
            workspace,
            include_config_py=include_config_py,
            max_diff_chars=max_diff_chars,
        )

    async def run_uat_check(
        case_ids: str = "",
        turn: int | None = None,
        runs: int = 1,
        limit: int | None = None,
        repo: Literal["dev", "uat"] = "dev",
    ) -> dict[str, Any]:
        """Run UAT batch evaluation against the configured target endpoint in 'dev' or 'uat'. Pass comma-separated case_ids (e.g. 'Q4') for targeted debugging, or leave empty for full regression."""
        req = UatRunRequest(case_ids=case_ids, turn=turn, runs=runs, limit=limit, repo=repo)
        return await uat_service.run_and_collect(workspace, req)

    tools: list[Callable[..., Any]] = [get_uat_summary, get_uat_case_detail, get_git_diff]
    if (workspace.uat_path or "").strip():
        tools.append(compare_dev_and_uat)
    if mode != "read_only":
        tools.append(run_uat_check)
    return tools


def build_workbench_hooks(
    registry: WorkspaceRegistry,
    uat_service: UatService,
    settings: WorkbenchSettings | None = None,
) -> WorkbenchHooks:
    def _resolve_ws(ws_id: str) -> WorkspaceContext:
        entry = registry.get_entry(ws_id)
        extra_paths: list[str] = []
        if entry.uat_path and entry.uat_path.strip():
            dev_resolved = Path(entry.path).expanduser().resolve()
            uat_resolved = Path(entry.uat_path).expanduser().resolve()
            if uat_resolved.is_dir() and uat_resolved != dev_resolved:
                extra_paths.append(str(uat_resolved))
        return WorkspaceContext(
            id=entry.id,
            name=entry.name,
            path=entry.path,
            extra_paths=extra_paths,
        )

    def _build_sys_instructions(ws: WorkspaceContext, mode: ExecutionMode) -> str:
        try:
            entry = registry.get_entry(ws.id)
            return build_system_instructions(entry, mode)
        except KeyError:
            return build_system_instructions(ws, mode)

    def _build_tools(ws: WorkspaceContext, mode: ExecutionMode) -> list[Callable[..., Any]]:
        entry = registry.get_entry(ws.id)
        return build_host_tools(entry, uat_service, mode)

    def _resolve_skills(_ws: WorkspaceContext | None) -> list[str]:
        configured = settings.resolved_skills_paths if settings is not None else []
        builtin_skills = (
            [_BUILTIN_WORKBENCH_SKILLS_DIR]
            if _BUILTIN_WORKBENCH_SKILLS_DIR.is_dir()
            else []
        )
        return merge_skills_paths(
            [SKILLS_ROOT] if SKILLS_ROOT.is_dir() else [],
            configured,
            builtin_skills,
            default_user_skills_paths(),
            existing_only=True,
        )

    def _on_mutated(ws: WorkspaceContext) -> dict[str, Any]:
        git_info = inspect_workspace_git(Path(ws.path))
        uat_git_dump: dict[str, Any] | None = None
        if ws.extra_paths:
            uat_git_dump = inspect_workspace_git(Path(ws.extra_paths[0])).model_dump()
        return {
            "type": "git_diff_updated",
            "workspace_id": ws.id,
            "git": git_info.model_dump(),
            "uat_git": uat_git_dump,
        }

    return WorkbenchHooks(
        resolve_workspace=_resolve_ws,
        build_system_instructions=_build_sys_instructions,
        build_host_tools=_build_tools,
        extra_read_only_tool_names=set(_ASK_READ_ONLY_TOOL_NAMES),
        read_only_blocked_tools=set(_ASK_READ_ONLY_BLOCKED_TOOLS),
        skills_paths=[str(SKILLS_ROOT)] if SKILLS_ROOT.is_dir() else [],
        resolve_skills_paths=_resolve_skills,
        destructive_reason=_ASK_DESTRUCTIVE_REASON,
        on_turn_mutated=_on_mutated,
    )
