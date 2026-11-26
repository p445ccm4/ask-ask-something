from __future__ import annotations

import difflib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from .ask_workbench_db import VALID_ENVS, EnvName
from .workspaces import (
    ProjectEntry,
    WorkspaceEntry,
    inspect_workspace_git,
    is_transient_service_relpath,
    normalize_service_relpath,
)

TargetEnv = EnvName
DeployMode = Literal["auto", "direct_push", "promote", "promote_from_dev"]

_DEFAULT_UPSTREAM: dict[EnvName, EnvName | None] = {
    "sbx": None,
    "dev": "sbx",
    "uat": "dev",
    "prod": "uat",
}

_PROMOTION_SKIP_PREFIXES = (
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    "node_modules/",
    ".next/",
    "scripts/",
    ".agents/",
    "tests/",
)

_PROMOTION_SKIP_EXACT = {
    "AGENTS.md",
    "uv.lock",
    ".DS_Store",
    "script - run in cloud shell",
}

PROTECTED_CONFIG_RELPATH = "src/config.py"


class DeployFileItem(BaseModel):
    path: str
    status: str  # M, A, D, ??, SYNC
    protected: bool = False
    reason: str | None = None


class DeployPreview(BaseModel):
    target_env: TargetEnv
    source_env: TargetEnv | None = None
    mode: Literal["direct_push", "promote", "promote_from_dev"]
    workspace_id: str
    workspace_name: str
    repo_toplevel: str | None = None
    service_subpath: str = "."
    branch: str | None = None
    remote_url: str | None = None
    changed_files: list[DeployFileItem] = Field(default_factory=list)
    protected_files: list[DeployFileItem] = Field(default_factory=list)
    unpushed_commits: list[str] = Field(default_factory=list)
    diff: str = ""
    can_deploy: bool = False
    blocking_reason: str | None = None
    suggested_commit_message: str = ""
    has_direct_target_changes: bool = False
    direct_target_files: list[str] = Field(default_factory=list)
    # Kept for clarity alongside generic target fields
    has_direct_uat_changes: bool = False
    direct_uat_files: list[str] = Field(default_factory=list)
    overlap_conflict_files: list[str] = Field(default_factory=list)
    available_source_envs: list[EnvName] = Field(default_factory=list)


class DeployResult(BaseModel):
    ok: bool
    target_env: TargetEnv
    source_env: TargetEnv | None = None
    commit_sha: str | None = None
    branch: str = "main"
    remote_url: str | None = None
    pushed_files: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


def _as_project(project_or_ws: ProjectEntry | WorkspaceEntry) -> ProjectEntry:
    if isinstance(project_or_ws, ProjectEntry):
        return project_or_ws
    return project_or_ws.to_project_entry()


def _run_git_checked(cwd: Path, args: list[str], logs: list[str], timeout: float = 60.0) -> str:
    cmd_display = f"git {' '.join(args)}"
    logs.append(f"$ {cmd_display}")
    res = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = (res.stdout or "") + (f"\n{res.stderr}" if res.stderr else "")
    if out.strip():
        logs.append(out.strip())
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({cmd_display}): {out.strip()}")
    return res.stdout.strip()


def _safe_service_relpath(root: Path, rel_path: str) -> Path:
    norm = rel_path.strip().lstrip("/")
    candidate = (root / norm).resolve()
    root_resolved = root.resolve()
    candidate.relative_to(root_resolved)
    return candidate


def _is_within_root(path: Path, root_resolved: Path) -> bool:
    try:
        path.resolve().relative_to(root_resolved)
        return True
    except (OSError, ValueError):
        return False


def _should_skip_promotion(rel_path: str) -> bool:
    norm = normalize_service_relpath(rel_path)
    if norm in _PROMOTION_SKIP_EXACT:
        return True
    if is_transient_service_relpath(norm):
        return True
    if any(norm.startswith(p) or f"/{p}" in norm for p in _PROMOTION_SKIP_PREFIXES):
        return True
    if norm.startswith(".") and norm not in {".dockerignore"}:
        return True
    return False


def _collect_env_promotion_changes(
    src_dir: Path,
    dst_dir: Path,
    *,
    src_label: str,
    dst_label: str,
    include_config_py: bool = False,
) -> tuple[list[DeployFileItem], list[DeployFileItem], str]:
    changed: list[DeployFileItem] = []
    protected: list[DeployFileItem] = []
    diff_chunks: list[str] = []

    src_resolved = src_dir.resolve()
    dst_resolved = dst_dir.resolve()

    for src_file in sorted(src_resolved.rglob("*")):
        if not src_file.is_file() or not _is_within_root(src_file, src_resolved):
            continue
        rel = src_file.relative_to(src_resolved).as_posix()
        if _should_skip_promotion(rel):
            continue

        dst_file = dst_resolved / rel
        if dst_file.exists() and not _is_within_root(dst_file, dst_resolved):
            continue
        src_bytes = src_file.read_bytes()
        dst_exists = dst_file.is_file()
        dst_bytes = dst_file.read_bytes() if dst_exists else b""

        if src_bytes == dst_bytes:
            continue

        if rel == PROTECTED_CONFIG_RELPATH and not include_config_py:
            protected.append(
                DeployFileItem(
                    path=rel,
                    status="PROTECTED",
                    protected=True,
                    reason=f"Preserving {dst_label.upper()} environment PROJECT_ID and configuration",
                )
            )
            continue

        status = "M" if dst_exists else "A"
        changed.append(
            DeployFileItem(
                path=rel,
                status=status,
                protected=(rel == PROTECTED_CONFIG_RELPATH),
            )
        )

        src_lines = src_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        dst_lines = dst_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        udiff = "".join(
            difflib.unified_diff(
                dst_lines,
                src_lines,
                fromfile=f"{dst_label}/{rel}" if dst_exists else "/dev/null",
                tofile=f"{src_label}/{rel}",
            )
        )
        if udiff.strip():
            diff_chunks.append(udiff.rstrip())

    return changed, protected, "\n\n".join(diff_chunks)


def compare_envs(
    project_or_ws: ProjectEntry | WorkspaceEntry,
    source_env: TargetEnv = "dev",
    target_env: TargetEnv = "uat",
    include_config_py: bool = True,
    max_diff_chars: int = 20000,
) -> dict[str, Any]:
    proj = _as_project(project_or_ws)
    src_raw = (proj.environments.get(source_env) or "").strip()
    dst_raw = (proj.environments.get(target_env) or "").strip()
    if not src_raw:
        return {"error": f"No {source_env.upper()} repository is configured for project '{proj.name}'."}
    if not dst_raw:
        return {"error": f"No {target_env.upper()} repository is configured for project '{proj.name}'."}

    src_root = Path(src_raw).expanduser().resolve()
    dst_root = Path(dst_raw).expanduser().resolve()
    if not src_root.is_dir():
        return {"error": f"{source_env.upper()} directory not found: {src_root}"}
    if not dst_root.is_dir():
        return {"error": f"{target_env.upper()} directory not found: {dst_root}"}

    changed, protected, diff_text = _collect_env_promotion_changes(
        src_root,
        dst_root,
        src_label=source_env,
        dst_label=target_env,
        include_config_py=include_config_py,
    )

    target_only_files: list[str] = []
    target_only_diffs: list[str] = []
    for dst_file in sorted(dst_root.rglob("*")):
        if not dst_file.is_file() or not _is_within_root(dst_file, dst_root):
            continue
        rel = dst_file.relative_to(dst_root).as_posix()
        if _should_skip_promotion(rel):
            continue
        if rel == PROTECTED_CONFIG_RELPATH and not include_config_py:
            continue
        if not (src_root / rel).is_file():
            target_only_files.append(rel)
            try:
                dst_lines = dst_file.read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)
                udiff = "".join(
                    difflib.unified_diff(
                        dst_lines,
                        [],
                        fromfile=f"{target_env}/{rel}",
                        tofile="/dev/null",
                    )
                )
                if udiff.strip():
                    target_only_diffs.append(udiff.rstrip())
            except OSError:
                pass

    combined_diff = "\n\n".join(part for part in [diff_text, *target_only_diffs] if part.strip())
    bounded_chars = max(1000, int(max_diff_chars))
    diff_truncated = len(combined_diff) > bounded_chars
    if diff_truncated:
        combined_diff = combined_diff[:bounded_chars] + "\n... [diff truncated]"

    src_git = inspect_workspace_git(src_root)
    dst_git = inspect_workspace_git(dst_root)

    return {
        "source_env": source_env,
        "target_env": target_env,
        "source_path": str(src_root),
        "target_path": str(dst_root),
        "source_branch": src_git.branch,
        "target_branch": dst_git.branch,
        "in_sync": not changed and not target_only_files,
        "changed_files": [f.model_dump() for f in changed],
        "protected_files": [f.model_dump() for f in protected],
        "target_only_files": target_only_files,
        # Backwards-compatible aliases
        "dev_path": str(src_root),
        "uat_path": str(dst_root),
        "dev_branch": src_git.branch,
        "uat_branch": dst_git.branch,
        "uat_only_files": target_only_files,
        "diff": combined_diff,
        "diff_truncated": diff_truncated,
    }


def compare_dev_and_uat(
    project_or_ws: ProjectEntry | WorkspaceEntry,
    include_config_py: bool = True,
    max_diff_chars: int = 20000,
) -> dict[str, Any]:
    return compare_envs(
        project_or_ws,
        source_env="dev",
        target_env="uat",
        include_config_py=include_config_py,
        max_diff_chars=max_diff_chars,
    )


def _resolve_source_env(
    proj: ProjectEntry,
    target_env: TargetEnv,
    explicit_source: TargetEnv | None,
) -> TargetEnv | None:
    if explicit_source and explicit_source != target_env and explicit_source in proj.environments:
        return explicit_source
    default_up = _DEFAULT_UPSTREAM.get(target_env)
    if default_up and default_up in proj.environments:
        return default_up
    # Fallback to any upstream env before target_env in order
    idx = VALID_ENVS.index(target_env)
    for prev in reversed(VALID_ENVS[:idx]):
        if prev in proj.environments:
            return prev
    return None


def preview_deploy(
    project_or_ws: ProjectEntry | WorkspaceEntry,
    target_env: TargetEnv,
    include_config_py: bool = False,
    deploy_mode: DeployMode = "auto",
    force_overwrite_uat: bool = False,
    source_env: TargetEnv | None = None,
    force_overwrite: bool | None = None,
) -> DeployPreview:
    proj = _as_project(project_or_ws)
    overwrite_flag = force_overwrite if force_overwrite is not None else force_overwrite_uat
    available_sources = [e for e in VALID_ENVS if e != target_env and e in proj.environments]

    target_raw = (proj.environments.get(target_env) or "").strip()
    if not target_raw:
        return DeployPreview(
            target_env=target_env,
            mode="direct_push",
            workspace_id=proj.id,
            workspace_name=proj.name,
            can_deploy=False,
            blocking_reason=f"No {target_env.upper()} repository path is configured for project '{proj.name}'.",
            available_source_envs=available_sources,
        )

    target_path = Path(target_raw).expanduser()
    service_slug = target_path.name
    if not target_path.is_dir():
        return DeployPreview(
            target_env=target_env,
            mode="direct_push",
            workspace_id=proj.id,
            workspace_name=proj.name,
            can_deploy=False,
            blocking_reason=f"{target_env.upper()} directory not found: {target_path}",
            available_source_envs=available_sources,
        )

    resolved_source = _resolve_source_env(proj, target_env, source_env)
    target_git = inspect_workspace_git(target_path)
    direct_files = [f.path for f in target_git.changed_files]
    direct_set = set(direct_files)
    has_direct = bool(direct_files)

    wants_promote = deploy_mode in ("promote", "promote_from_dev")
    if deploy_mode == "direct_push" or not resolved_source:
        resolved_mode: Literal["direct_push", "promote_from_dev", "promote"] = "direct_push"
    elif wants_promote:
        resolved_mode = "promote_from_dev" if (resolved_source == "dev" and target_env == "uat") else "promote"
    else:
        # "auto": sbx & dev default to direct_push; uat & prod promote unless direct local target edits exist
        if target_env in ("sbx", "dev"):
            resolved_mode = "direct_push"
        else:
            src_path = Path(proj.environments[resolved_source]).expanduser()
            promo_files_probe, _, _ = _collect_env_promotion_changes(
                src_path,
                target_path,
                src_label=resolved_source,
                dst_label=target_env,
                include_config_py=include_config_py,
            )
            promo_paths_probe = {f.path for f in promo_files_probe}
            if (has_direct and (not promo_files_probe or promo_paths_probe.issubset(direct_set))) or (
                not promo_files_probe and bool(target_git.unpushed_commits)
            ):
                resolved_mode = "direct_push"
            else:
                resolved_mode = (
                    "promote_from_dev"
                    if (resolved_source == "dev" and target_env == "uat")
                    else "promote"
                )

    require_main = target_env != "sbx"

    if resolved_mode == "direct_push":
        files = [DeployFileItem(path=f.path, status=f.status) for f in target_git.changed_files]
        blocking: str | None = None
        if not target_git.is_git_repo:
            blocking = f"{target_env.upper()} path is not inside a Git repository."
        elif require_main and target_git.branch != "main":
            blocking = f"Expected {target_env.upper()} branch 'main', but repo is on '{target_git.branch}'."
        elif not files and not target_git.unpushed_commits:
            blocking = f"No uncommitted changes or unpushed commits found in {target_env.upper()}."

        return DeployPreview(
            target_env=target_env,
            source_env=resolved_source,
            mode="direct_push",
            workspace_id=proj.id,
            workspace_name=proj.name,
            repo_toplevel=target_git.git_toplevel,
            service_subpath=target_git.service_subpath,
            branch=target_git.branch,
            remote_url=target_git.remote_url,
            changed_files=files,
            protected_files=[],
            unpushed_commits=target_git.unpushed_commits,
            diff=target_git.diff,
            can_deploy=(blocking is None),
            blocking_reason=blocking,
            suggested_commit_message=f"fix({service_slug}): update {service_slug} in {target_env}",
            has_direct_target_changes=has_direct,
            direct_target_files=direct_files,
            has_direct_uat_changes=has_direct if target_env == "uat" else False,
            direct_uat_files=direct_files if target_env == "uat" else [],
            overlap_conflict_files=[],
            available_source_envs=available_sources,
        )

    assert resolved_source is not None
    src_path = Path(proj.environments[resolved_source]).expanduser()
    if not src_path.is_dir():
        return DeployPreview(
            target_env=target_env,
            source_env=resolved_source,
            mode=resolved_mode,
            workspace_id=proj.id,
            workspace_name=proj.name,
            can_deploy=False,
            blocking_reason=f"Source {resolved_source.upper()} directory not found: {src_path}",
            available_source_envs=available_sources,
        )

    promo_files, protected_files, promo_diff = _collect_env_promotion_changes(
        src_path,
        target_path,
        src_label=resolved_source,
        dst_label=target_env,
        include_config_py=include_config_py,
    )
    promo_paths = {f.path for f in promo_files}
    overlap_conflict_files = sorted(promo_paths & direct_set)

    blocking = None
    if not target_git.is_git_repo:
        blocking = f"{target_env.upper()} path is not a Git repository."
    elif require_main and target_git.branch != "main":
        blocking = f"Expected {target_env.upper()} branch 'main', but repo is on '{target_git.branch}'."
    elif overlap_conflict_files and not overwrite_flag:
        blocking = (
            f"Direct uncommitted {target_env.upper()} changes in "
            f"{', '.join(overlap_conflict_files)} overlap with {resolved_source.upper()} -> {target_env.upper()} promotion. "
            f"Switch to 'Push Direct {target_env.upper()} Changes' or enable overwrite."
        )
    elif not promo_files and not target_git.unpushed_commits:
        blocking = (
            f"{target_env.upper()} service code is already in sync with {resolved_source.upper()} "
            "(and has no unpushed commits)."
        )

    return DeployPreview(
        target_env=target_env,
        source_env=resolved_source,
        mode=resolved_mode,
        workspace_id=proj.id,
        workspace_name=proj.name,
        repo_toplevel=target_git.git_toplevel,
        service_subpath=target_git.service_subpath,
        branch=target_git.branch,
        remote_url=target_git.remote_url,
        changed_files=promo_files,
        protected_files=protected_files,
        unpushed_commits=target_git.unpushed_commits,
        diff=promo_diff,
        can_deploy=(blocking is None),
        blocking_reason=blocking,
        suggested_commit_message=f"fix({service_slug}): promote {service_slug} from {resolved_source} to {target_env}",
        has_direct_target_changes=has_direct,
        direct_target_files=direct_files,
        has_direct_uat_changes=has_direct if target_env == "uat" else False,
        direct_uat_files=direct_files if target_env == "uat" else [],
        overlap_conflict_files=overlap_conflict_files,
        available_source_envs=available_sources,
    )


def execute_deploy(
    workspace: ProjectEntry | WorkspaceEntry,
    target_env: TargetEnv,
    commit_message: str,
    selected_files: list[str] | None = None,
    include_config_py: bool = False,
    deploy_mode: DeployMode = "auto",
    force_overwrite_uat: bool = False,
    source_env: TargetEnv | None = None,
    force_overwrite: bool | None = None,
) -> DeployResult:
    """Human-initiated scoped commit + git push. Never exposed as an agent tool."""
    proj = _as_project(workspace)
    overwrite_flag = force_overwrite if force_overwrite is not None else force_overwrite_uat
    logs: list[str] = []
    preview = preview_deploy(
        proj,
        target_env,
        include_config_py=include_config_py,
        deploy_mode=deploy_mode,
        force_overwrite_uat=overwrite_flag,
        source_env=source_env,
    )
    if not preview.can_deploy:
        raise ValueError(preview.blocking_reason or "Deployment preconditions not met.")

    target_service_dir = Path(proj.path_for_env(target_env)).resolve()
    promoted_rel_set: set[str] | None = None

    if preview.mode in ("promote", "promote_from_dev") and preview.source_env:
        src_service_dir = Path(proj.path_for_env(preview.source_env)).resolve()
        candidate_paths = [f.path for f in preview.changed_files]
        files_to_sync = (
            [p for p in candidate_paths if p in set(selected_files)]
            if selected_files is not None
            else candidate_paths
        )
        promoted_rel_set = set(files_to_sync)
        for rel in files_to_sync:
            if rel == PROTECTED_CONFIG_RELPATH and not include_config_py:
                continue
            src_f = _safe_service_relpath(src_service_dir, rel)
            dst_f = _safe_service_relpath(target_service_dir, rel)
            if src_f.is_file():
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_f, dst_f)
                logs.append(f"Synced {preview.source_env.upper()} -> {target_env.upper()}: {rel}")

    git_info = inspect_workspace_git(target_service_dir)
    if not git_info.is_git_repo or not git_info.git_toplevel or not git_info.branch:
        raise ValueError("Target directory is not a valid Git repository.")

    expected_branch = "main" if target_env != "sbx" else git_info.branch
    if target_env != "sbx" and git_info.branch != "main":
        raise ValueError(f"Refusing to push: repository is on branch '{git_info.branch}', expected 'main'.")

    toplevel = Path(git_info.git_toplevel).resolve()
    sub = git_info.service_subpath

    available_changed = [f.path for f in git_info.changed_files]
    if selected_files is not None:
        chosen_rel_files = [p for p in available_changed if p in set(selected_files)]
    elif promoted_rel_set is not None:
        chosen_rel_files = [p for p in available_changed if p in promoted_rel_set]
    else:
        chosen_rel_files = available_changed

    repo_rel_specs: list[str] = []
    for rel in chosen_rel_files:
        _safe_service_relpath(target_service_dir, rel)
        if is_transient_service_relpath(rel):
            continue
        repo_rel = rel if sub == "." else f"{sub}/{rel}"
        repo_rel_specs.append(repo_rel)

    if repo_rel_specs:
        msg = commit_message.strip()
        if not msg:
            raise ValueError("A commit message is required when committing file changes.")
        _run_git_checked(toplevel, ["add", "-A", "--", *repo_rel_specs], logs)
        _run_git_checked(toplevel, ["commit", "-m", msg, "--", *repo_rel_specs], logs)
    elif not git_info.unpushed_commits:
        raise ValueError("No files selected and no unpushed commits to push.")

    if git_info.remote_url:
        _run_git_checked(toplevel, ["fetch", "origin", expected_branch], logs, timeout=60.0)
        behind_res = subprocess.run(
            ["git", "-C", str(toplevel), "rev-list", "--count", f"HEAD..origin/{expected_branch}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if behind_res.returncode == 0 and int((behind_res.stdout or "0").strip() or "0") > 0:
            _run_git_checked(
                toplevel,
                ["pull", "--rebase", "--autostash", "origin", expected_branch],
                logs,
                timeout=90.0,
            )

        _run_git_checked(toplevel, ["push", "origin", expected_branch], logs, timeout=90.0)
    else:
        raise ValueError("No 'origin' git remote configured on repository.")

    sha = _run_git_checked(toplevel, ["rev-parse", "--short", "HEAD"], logs)
    return DeployResult(
        ok=True,
        target_env=target_env,
        source_env=preview.source_env if preview.mode != "direct_push" else None,
        commit_sha=sha,
        branch=expected_branch,
        remote_url=git_info.remote_url,
        pushed_files=chosen_rel_files,
        logs=logs,
    )
