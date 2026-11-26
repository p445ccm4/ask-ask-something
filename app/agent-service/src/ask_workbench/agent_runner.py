from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

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

from .ask_workbench_db import VALID_ENVS, EnvName
from .config import SKILLS_ROOT
from .deploy_service import compare_envs as _compare_envs
from .uat_service import EvalRunRequest, EvalService
from .workspaces import (
    ProjectEntry,
    ProjectRegistry,
    WorkspaceEntry,
    inspect_workspace_git,
)

_BUILTIN_WORKBENCH_SKILLS_DIR = Path(ag_workbench.__file__).resolve().parent / "skills"

_ASK_READ_ONLY_TOOL_NAMES = {
    "list_eval_suites",
    "get_eval_summary",
    "query_eval_cases",
    "get_eval_case_detail",
    "get_git_diff",
    "compare_envs",
}

_ASK_READ_ONLY_BLOCKED_TOOLS = {
    "create_or_update_eval_suite",
    "upsert_eval_cases",
    "import_xlsx_suite",
    "run_eval_check",
}

_ASK_DESTRUCTIVE_REASON = (
    "Remote pushes (git push), destructive deletes (rm -rf), and cloud deployments are blocked for the AI agent. "
    "Use the Deploy / Promote action in the UI to push changes."
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


def _as_project(project_or_ws: ProjectEntry | WorkspaceEntry) -> ProjectEntry:
    if isinstance(project_or_ws, ProjectEntry):
        return project_or_ws
    return project_or_ws.to_project_entry()


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


def build_system_instructions(
    project_or_ws: ProjectEntry | WorkspaceEntry | WorkspaceContext,
    mode: ExecutionMode,
) -> str:
    mode_note = {
        "read_only": (
            "CURRENT EXECUTION MODE: READ-ONLY INSPECT. "
            "You can inspect files, git diffs, and Eval results/logs, but you MUST NOT attempt edits, suite mutations, or shell commands. "
            "Provide concrete root-cause analysis and exact proposed file/line fixes."
        ),
        "ask_before_fix": (
            "CURRENT EXECUTION MODE: ASK-BEFORE-FIX (Human-in-the-Loop). "
            "Read/search/eval-query tools run automatically, while file edits, shell commands, eval suite edits, and eval runs pause for user approval in the UI."
        ),
        "sandboxed_auto": (
            "CURRENT EXECUTION MODE: SANDBOXED AUTO-FIX. "
            "You may edit files inside the mounted project repositories and run local tests inside the Linux sandbox. "
            "`git push` and destructive commands remain blocked — the human user pushes via the UI Deploy / Promote modal."
        ),
        "unsandboxed_auto": (
            "CURRENT EXECUTION MODE: UNSANDBOXED AUTO-FIX. "
            "You may edit files inside the mounted project repositories and run shell commands directly on the host without the Linux sandbox or destructive-command blocks. "
            "Still let the human user push changes via the UI Deploy / Promote modal."
        ),
    }[mode]

    env_lines: list[str] = []
    active_env_label = "DEV"
    primary_path = project_or_ws.path
    if isinstance(project_or_ws, (ProjectEntry, WorkspaceEntry)):
        proj = _as_project(project_or_ws)
        active_env_label = proj.active_env.upper()
        primary_path = proj.path
        for env in VALID_ENVS:
            p = proj.environments.get(env)
            if p and p.strip():
                marker = " (ACTIVE)" if env == proj.active_env else ""
                env_lines.append(f"- {env.upper()}{marker}: '{p}'")
    else:
        env_lines.append(f"- Primary: '{project_or_ws.path}'")
        for idx, ep in enumerate(getattr(project_or_ws, "extra_paths", []) or [], 1):
            if ep and ep.strip():
                env_lines.append(f"- Extra repo {idx}: '{ep}'")

    env_section = ""
    if len(env_lines) > 1:
        env_section = (
            "\nMULTI-ENVIRONMENT PROJECT WORKSPACE (ALL EDITABLE):\n"
            + "\n".join(env_lines)
            + "\n- All configured environment repositories above are mounted as editable workspaces for built-in file tools "
            "(`view_file`, `search_directory`, `find_file`, `list_directory`, `edit_file`, `create_file`) and `run_command`.\n"
            f"- Relative paths default to the currently active {active_env_label} repository ('{primary_path}'). "
            "Always pass explicit/absolute paths when inspecting or editing files in another environment, and verify `Cwd` when running shell commands.\n"
            "- Use `compare_envs(source_env=..., target_env=...)` to diff code/config between environments (e.g. `sbx` vs `dev`, `dev` vs `uat`, `uat` vs `prod`).\n"
            "- Remember that `src/config.py` holds environment-specific `PROJECT_ID` / bucket configuration; do not overwrite another environment's `src/config.py` unless explicitly requested.\n"
        )
    elif env_lines:
        env_section = "\nCONFIGURED ENVIRONMENT REPOSITORY:\n" + "\n".join(env_lines) + "\n"

    return (
        f"You are the AskAsk* Maintainer Agent for project '{project_or_ws.name}' "
        f"(active environment: {active_env_label}, path: '{primary_path}').\n"
        f"{mode_note}\n"
        f"{env_section}\n"
        "SQLITE EVAL SSOT & ZERO TARGET-REPO POLLUTION RULE:\n"
        "- ALL Eval Suites, Eval Cases, Judge Rubrics, Endpoint Configs, Run Results, and Logs are stored centrally in the workbench SQLite database (Single Source of Truth) — NOT in `<repo>/scripts/uat/`.\n"
        "- NEVER create, update, or commit `scripts/uat/*`, `.json`, `.csv`, or `.xlsx` eval files inside any target agent repository.\n"
        "- Always use the DB-backed Eval host tools (`list_eval_suites`, `get_eval_summary`, `query_eval_cases`, `get_eval_case_detail`, `create_or_update_eval_suite`, `upsert_eval_cases`, `import_xlsx_suite`, `run_eval_check`) instead of shelling out to `run_uat_batch.py` or writing JSON files.\n\n"
        "ARCHITECTURE & TOOL BOUNDARIES:\n"
        "- Built-in file tools (`view_file`, `search_directory`, `find_file`, `list_directory`, `edit_file`, `create_file`) "
        "and `run_command` are strictly scoped to the configured project workspace root(s).\n"
        "- Use `attach_output_file(file_path, caption)` to deliver any file, report, or image directly to the user in the chatbox.\n"
        f"- For interactive HTML widgets/mockups, follow the `generative_ui` skill (save self-contained `.html` files under `{AG_ARTIFACTS_DIR_NAME}/` and embed compact widgets via `<agent-embed src=\"{AG_ARTIFACTS_DIR_NAME}/widget.html\"></agent-embed>` or link larger dashboards with standard markdown links).\n"
        "- When `search_web` is enabled, use it to look up up-to-date external documentation, releases, or references when needed.\n"
        "- Follow the `ask-ask-something` debugging discipline: inspect actual vs expected answer/behavior & retrieved sources (`get_eval_case_detail`) -> "
        "inspect prompts/RAG/service code -> make targeted fixes -> verify with targeted `run_eval_check(case_ids=...)` and `runs=5` stability check -> "
        "remind/run full regression (`run_eval_check(case_ids='')`).\n"
        "- NEVER attempt `git push`. When fixes are verified, summarize the git diff and tell the user they can use Deploy / Promote in the header."
    )


def build_host_tools(
    project_or_ws: ProjectEntry | WorkspaceEntry,
    eval_service: EvalService,
    mode: ExecutionMode,
    *,
    registry: ProjectRegistry | None = None,
) -> list[Callable[..., Any]]:
    initial_proj = _as_project(project_or_ws)

    def _current_project() -> ProjectEntry:
        if registry is not None:
            try:
                return registry.get_entry(initial_proj.id)
            except KeyError:
                return initial_proj
        return initial_proj

    async def list_eval_suites(
        env: EnvName | None = None,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List Eval Suites stored in SQLite for the active (or specified) project environment."""
        proj = _current_project()
        try:
            res = eval_service.list_suites(proj, env=env, search=search, limit=limit, offset=offset)
            return {
                "project": proj.name,
                "env": env or proj.active_env,
                **res,
            }
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return {"error": str(exc), "env": env or proj.active_env}

    async def get_eval_summary(
        env: EnvName | None = None,
        suite_id: str | None = None,
    ) -> dict[str, Any]:
        """Return overall Eval score, FAIL/PARTIAL case list, endpoint config, and rubric preview from SQLite."""
        proj = _current_project()
        target_env = env or proj.active_env
        try:
            overview = eval_service.get_overview(
                proj,
                env=target_env,
                suite_id=suite_id,
                status="ALL",
                limit=50,
                offset=0,
                include_details=False,
            )
            flagged_page = None
            active_suite = overview.get("active_suite")
            if active_suite:
                fail_res = eval_service.query_cases(
                    proj,
                    env=target_env,
                    suite_id=active_suite["id"],
                    status="FAIL",
                    limit=50,
                )
                partial_res = eval_service.query_cases(
                    proj,
                    env=target_env,
                    suite_id=active_suite["id"],
                    status="PARTIAL",
                    limit=50,
                )
                flagged_page = [
                    {
                        "id": c["id"],
                        "status": c["status"],
                        "score": c["score"],
                        "comment": c["comment"],
                    }
                    for c in [*fail_res["cases"], *partial_res["cases"]]
                ]
            return {
                "project": proj.name,
                "env": target_env,
                "suites_total": overview["suites_total"],
                "active_suite": active_suite,
                "has_config": overview["has_config"],
                "has_questions": overview["has_questions"],
                "has_results": overview["has_results"],
                "summary": overview["summary"],
                "flagged_cases": flagged_page or [],
                "rubric_preview": (overview.get("rubric_preview") or "")[:3000],
            }
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return {"error": str(exc), "env": target_env}

    async def query_eval_cases(
        env: EnvName | None = None,
        suite_id: str | None = None,
        status: str = "ALL",
        turn_filter: str = "ALL",
        search: str = "",
        sort_by: str = "ORDER",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search/filter paginated eval cases in SQLite by status (ALL/PASS/PARTIAL/FAIL/PENDING), turn_filter (ALL/SINGLE/MULTI), or search keyword."""
        proj = _current_project()
        target_env = env or proj.active_env
        try:
            res = eval_service.query_cases(
                proj,
                env=target_env,
                suite_id=suite_id,
                status=status,
                turn_filter=turn_filter,
                search=search,
                sort_by=sort_by,
                limit=limit,
                offset=offset,
                include_details=False,
            )
            return {"project": proj.name, "env": target_env, **res}
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return {"error": str(exc), "env": target_env}

    async def get_eval_case_detail(
        case_id: str,
        env: EnvName | None = None,
        suite_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch full turn questions, expected answers/behaviors, actual answers, retrieved sources, and judge reviews for an eval case ID (e.g. 'Q4')."""
        proj = _current_project()
        target_env = env or proj.active_env
        try:
            return eval_service.get_case_detail(
                proj, case_id, env=target_env, suite_id=suite_id
            )
        except (ValueError, FileNotFoundError, KeyError) as exc:
            return {"error": str(exc), "env": target_env, "case_id": case_id}

    async def get_git_diff(env: EnvName | None = None) -> dict[str, Any]:
        """Inspect branch, modified files, and unified git diff for the active (or specified: sbx/dev/uat/prod) repository."""
        proj = _current_project()
        target_env = (env or proj.active_env).lower()
        try:
            path_str = proj.path_for_env(target_env)
        except ValueError as exc:
            return {"error": str(exc), "env": target_env}
        info = inspect_workspace_git(Path(path_str).expanduser())
        return {**info.model_dump(), "env": target_env}

    async def compare_envs(
        source_env: EnvName = "dev",
        target_env: EnvName = "uat",
        include_config_py: bool = True,
        max_diff_chars: int = 20000,
    ) -> dict[str, Any]:
        """Compare code/config files and unified diffs between any two configured project environments (sbx, dev, uat, prod)."""
        proj = _current_project()
        return _compare_envs(
            proj,
            source_env=source_env,
            target_env=target_env,
            include_config_py=include_config_py,
            max_diff_chars=max_diff_chars,
        )

    async def create_or_update_eval_suite(
        name: str,
        env: EnvName | None = None,
        suite_id: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        rubric_md: str | None = None,
        is_default: bool | None = None,
    ) -> dict[str, Any]:
        """Create or update an Eval Suite's endpoint config, domain rubric, or metadata directly in SQLite (never writes to target repo)."""
        proj = _current_project()
        try:
            suite = eval_service.create_or_update_suite(
                proj,
                env=env,
                suite_id=suite_id,
                name=name,
                description=description,
                config=config,
                rubric_md=rubric_md,
                is_default=is_default,
            )
            return {"ok": True, "suite": suite}
        except (ValueError, KeyError) as exc:
            return {"error": str(exc)}

    async def upsert_eval_cases(
        suite_id: str,
        cases: list[dict[str, Any]],
        env: EnvName | None = None,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        """Insert or update eval test cases (with single/multi-turn questions, expected_answer, expected_behavior) directly in SQLite."""
        proj = _current_project()
        target_env = env or proj.active_env
        try:
            suite = eval_service.db.get_suite(suite_id)
            if suite["project_id"] != proj.id or suite["env"] != target_env:
                return {
                    "error": f"Eval suite '{suite_id}' does not belong to {proj.name} ({target_env.upper()})."
                }
            cnt = eval_service.upsert_cases(suite_id, cases, replace_all=replace_all)
            return {
                "ok": True,
                "suite_id": suite_id,
                "upserted_count": cnt,
                "summary": eval_service.db.get_suite_summary(suite_id),
            }
        except (ValueError, KeyError) as exc:
            return {"error": str(exc)}

    async def import_xlsx_suite(
        xlsx_path: str,
        suite_name: str | None = None,
        env: EnvName | None = None,
        suite_id: str | None = None,
        mapping: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Import an Excel (.xlsx) test sheet from local disk directly into SQLite (and stores the template centrally outside target repos)."""
        proj = _current_project()
        p = Path(xlsx_path).expanduser()
        if not p.is_file():
            return {"error": f"Excel file not found: {p}"}
        try:
            res = eval_service.import_xlsx_bytes(
                proj,
                env=env,
                content=p.read_bytes(),
                filename=p.name,
                suite_name=suite_name,
                suite_id=suite_id,
                mapping=mapping,
            )
            return {
                "ok": True,
                "suite_id": res["suite"]["id"],
                "suite_name": res["suite"]["name"],
                "imported_cases": res["imported_cases"],
                "total_turns": res["total_turns"],
                "skipped_empty_rows": res["skipped_empty_rows"],
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def run_eval_check(
        case_ids: str = "",
        turn: int | None = None,
        runs: int = 1,
        limit: int | None = None,
        env: EnvName | None = None,
        suite_id: str | None = None,
    ) -> dict[str, Any]:
        """Run Eval batch against the configured endpoint in SQLite for the active (or specified) environment. Pass comma-separated case_ids for targeted debugging or leave empty for full regression."""
        proj = _current_project()
        req = EvalRunRequest(
            suite_id=suite_id,
            case_ids=case_ids,
            turn=turn,
            runs=runs,
            limit=limit,
            env=env,
        )
        return await eval_service.run_and_collect(proj, req)

    tools: list[Callable[..., Any]] = [
        list_eval_suites,
        get_eval_summary,
        query_eval_cases,
        get_eval_case_detail,
        get_git_diff,
    ]
    if len(initial_proj.configured_envs) >= 2:
        tools.append(compare_envs)
    if mode != "read_only":
        tools.extend(
            [
                create_or_update_eval_suite,
                upsert_eval_cases,
                import_xlsx_suite,
                run_eval_check,
            ]
        )
    return tools


def build_workbench_hooks(
    registry: ProjectRegistry,
    eval_service: EvalService,
    settings: WorkbenchSettings | None = None,
) -> WorkbenchHooks:
    def _resolve_ws(project_id: str) -> WorkspaceContext:
        entry = registry.get_entry(project_id)
        primary_path = entry.path
        primary_resolved = Path(primary_path).expanduser().resolve()

        extra_paths: list[str] = []
        seen: set[Path] = {primary_resolved}
        for env in VALID_ENVS:
            raw = entry.environments.get(env)
            if not raw or not raw.strip():
                continue
            resolved = Path(raw).expanduser().resolve()
            if resolved.is_dir() and resolved not in seen:
                seen.add(resolved)
                extra_paths.append(str(resolved))

        return WorkspaceContext(
            id=entry.id,
            name=entry.name,
            path=primary_path,
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
        return build_host_tools(entry, eval_service, mode, registry=registry)

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
        env_git: dict[str, Any] = {}
        active_git: dict[str, Any] | None = None
        uat_git_dump: dict[str, Any] | None = None
        try:
            entry = registry.get_entry(ws.id)
            for env in entry.configured_envs:
                p = Path(entry.environments[env]).expanduser()
                info = inspect_workspace_git(p).model_dump()
                env_git[env] = info
                if env == entry.active_env:
                    active_git = info
                if env == "uat":
                    uat_git_dump = info
        except KeyError:
            pass

        if active_git is None:
            active_git = inspect_workspace_git(Path(ws.path)).model_dump()
        if uat_git_dump is None and ws.extra_paths:
            uat_git_dump = inspect_workspace_git(Path(ws.extra_paths[0])).model_dump()

        return {
            "type": "git_diff_updated",
            "workspace_id": ws.id,
            "project_id": ws.id,
            "git": active_git,
            "env_git": env_git,
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
