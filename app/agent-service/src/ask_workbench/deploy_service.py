from __future__ import annotations

import difflib
import shutil
import subprocess
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

from .workspaces import WorkspaceEntry, inspect_workspace_git, is_transient_service_relpath

TargetEnv = Literal["dev", "uat"]

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
    mode: Literal["direct_push", "promote_from_dev"]
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


class DeployResult(BaseModel):
    ok: bool
    target_env: TargetEnv
    commit_sha: str | None = None
    branch: str = "main"
    remote_url: str | None = None
    pushed_files: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)


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


def _should_skip_promotion(rel_path: str) -> bool:
    norm = rel_path.strip().lstrip("./")
    if norm in _PROMOTION_SKIP_EXACT:
        return True
    if is_transient_service_relpath(norm):
        return True
    if any(norm.startswith(p) or f"/{p}" in norm for p in _PROMOTION_SKIP_PREFIXES):
        return True
    if norm.startswith(".") and norm not in {".dockerignore"}:
        return True
    return False


def _collect_dev_to_uat_changes(
    dev_dir: Path,
    uat_dir: Path,
    include_config_py: bool = False,
) -> tuple[list[DeployFileItem], list[DeployFileItem], str]:
    changed: list[DeployFileItem] = []
    protected: list[DeployFileItem] = []
    diff_chunks: list[str] = []

    dev_resolved = dev_dir.resolve()
    uat_resolved = uat_dir.resolve()

    for src_file in sorted(dev_resolved.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(dev_resolved).as_posix()
        if _should_skip_promotion(rel):
            continue

        dst_file = uat_resolved / rel
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
                    reason="Preserving UAT environment PROJECT_ID and bucket configuration",
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
                fromfile=f"uat/{rel}" if dst_exists else "/dev/null",
                tofile=f"dev/{rel}",
            )
        )
        if udiff.strip():
            diff_chunks.append(udiff.rstrip())

    return changed, protected, "\n\n".join(diff_chunks)


def preview_deploy(
    workspace: WorkspaceEntry,
    target_env: TargetEnv,
    include_config_py: bool = False,
) -> DeployPreview:
    ws_path = Path(workspace.path)
    service_slug = ws_path.name

    if target_env == "dev":
        git_info = inspect_workspace_git(ws_path)
        files = [DeployFileItem(path=f.path, status=f.status) for f in git_info.changed_files]
        blocking: str | None = None
        if not git_info.is_git_repo:
            blocking = "Workspace is not inside a Git repository."
        elif git_info.branch != "main":
            blocking = f"Expected branch 'main', but repo is on '{git_info.branch}'."
        elif not files and not git_info.unpushed_commits:
            blocking = "No uncommitted changes or unpushed commits found for this service."

        return DeployPreview(
            target_env="dev",
            mode="direct_push",
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            repo_toplevel=git_info.git_toplevel,
            service_subpath=git_info.service_subpath,
            branch=git_info.branch,
            remote_url=git_info.remote_url,
            changed_files=files,
            protected_files=[],
            unpushed_commits=git_info.unpushed_commits,
            diff=git_info.diff,
            can_deploy=(blocking is None),
            blocking_reason=blocking,
            suggested_commit_message=f"fix({service_slug}): update {service_slug} in dev",
        )

    # target_env == "uat"
    if workspace.env == "uat" or not workspace.uat_path:
        target_path = Path(workspace.uat_path) if workspace.uat_path else ws_path
        if workspace.env != "uat" and not workspace.uat_path:
            return DeployPreview(
                target_env="uat",
                mode="direct_push",
                workspace_id=workspace.id,
                workspace_name=workspace.name,
                can_deploy=False,
                blocking_reason="No paired UAT repository path is configured for this workspace.",
            )
        git_info = inspect_workspace_git(target_path)
        files = [DeployFileItem(path=f.path, status=f.status) for f in git_info.changed_files]
        blocking = None
        if not git_info.is_git_repo:
            blocking = "UAT directory is not inside a Git repository."
        elif git_info.branch != "main":
            blocking = f"Expected UAT branch 'main', but repo is on '{git_info.branch}'."
        elif not files and not git_info.unpushed_commits:
            blocking = "No uncommitted changes or unpushed commits found in UAT."
        return DeployPreview(
            target_env="uat",
            mode="direct_push",
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            repo_toplevel=git_info.git_toplevel,
            service_subpath=git_info.service_subpath,
            branch=git_info.branch,
            remote_url=git_info.remote_url,
            changed_files=files,
            unpushed_commits=git_info.unpushed_commits,
            diff=git_info.diff,
            can_deploy=(blocking is None),
            blocking_reason=blocking,
            suggested_commit_message=f"fix({service_slug}): update {service_slug} in uat",
        )

    # Promote from DEV workspace -> paired UAT workspace
    uat_path = Path(workspace.uat_path)
    if not uat_path.is_dir():
        return DeployPreview(
            target_env="uat",
            mode="promote_from_dev",
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            can_deploy=False,
            blocking_reason=f"Paired UAT directory not found: {uat_path}",
        )

    uat_git = inspect_workspace_git(uat_path)
    promo_files, protected_files, promo_diff = _collect_dev_to_uat_changes(
        ws_path, uat_path, include_config_py=include_config_py
    )

    seen_paths = {f.path for f in promo_files}
    for uf in uat_git.changed_files:
        if uf.path not in seen_paths:
            promo_files.append(DeployFileItem(path=uf.path, status=uf.status))

    combined_diff = "\n\n".join(p for p in [promo_diff, uat_git.diff] if p.strip())
    blocking = None
    if not uat_git.is_git_repo:
        blocking = "Paired UAT path is not a Git repository."
    elif uat_git.branch != "main":
        blocking = f"Expected UAT branch 'main', but repo is on '{uat_git.branch}'."
    elif not promo_files and not uat_git.unpushed_commits:
        blocking = "UAT service code is already in sync with DEV (and has no unpushed commits)."

    return DeployPreview(
        target_env="uat",
        mode="promote_from_dev",
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        repo_toplevel=uat_git.git_toplevel,
        service_subpath=uat_git.service_subpath,
        branch=uat_git.branch,
        remote_url=uat_git.remote_url,
        changed_files=promo_files,
        protected_files=protected_files,
        unpushed_commits=uat_git.unpushed_commits,
        diff=combined_diff,
        can_deploy=(blocking is None),
        blocking_reason=blocking,
        suggested_commit_message=f"fix({service_slug}): sync {service_slug} changes from dev to uat",
    )


def execute_deploy(
    workspace: WorkspaceEntry,
    target_env: TargetEnv,
    commit_message: str,
    selected_files: list[str] | None = None,
    include_config_py: bool = False,
) -> DeployResult:
    """Human-initiated scoped commit + git push origin main. Never exposed as an agent tool."""
    logs: list[str] = []
    preview = preview_deploy(workspace, target_env, include_config_py=include_config_py)
    if not preview.can_deploy:
        raise ValueError(preview.blocking_reason or "Deployment preconditions not met.")

    if target_env == "dev":
        target_service_dir = Path(workspace.path).resolve()
    elif preview.mode == "promote_from_dev":
        assert workspace.uat_path is not None
        dev_service_dir = Path(workspace.path).resolve()
        target_service_dir = Path(workspace.uat_path).resolve()
        candidate_paths = [f.path for f in preview.changed_files]
        files_to_sync = (
            [p for p in candidate_paths if p in set(selected_files)]
            if selected_files is not None
            else candidate_paths
        )
        for rel in files_to_sync:
            if rel == PROTECTED_CONFIG_RELPATH and not include_config_py:
                continue
            src_f = _safe_service_relpath(dev_service_dir, rel)
            dst_f = _safe_service_relpath(target_service_dir, rel)
            if src_f.is_file():
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_f, dst_f)
                logs.append(f"Synced DEV -> UAT: {rel}")
    else:
        target_service_dir = (
            Path(workspace.uat_path).resolve()
            if workspace.uat_path
            else Path(workspace.path).resolve()
        )

    git_info = inspect_workspace_git(target_service_dir)
    if not git_info.is_git_repo or not git_info.git_toplevel:
        raise ValueError("Target directory is not a valid Git repository.")
    if git_info.branch != "main":
        raise ValueError(f"Refusing to push: repository is on branch '{git_info.branch}', expected 'main'.")

    toplevel = Path(git_info.git_toplevel).resolve()
    sub = git_info.service_subpath

    available_changed = [f.path for f in git_info.changed_files]
    chosen_rel_files = (
        [p for p in available_changed if p in set(selected_files)]
        if selected_files is not None
        else available_changed
    )

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
        _run_git_checked(toplevel, ["fetch", "origin", "main"], logs, timeout=60.0)
        behind_res = subprocess.run(
            ["git", "-C", str(toplevel), "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True,
            text=True,
            check=False,
        )
        if behind_res.returncode == 0 and int((behind_res.stdout or "0").strip() or "0") > 0:
            _run_git_checked(toplevel, ["pull", "--rebase", "--autostash", "origin", "main"], logs, timeout=90.0)

        _run_git_checked(toplevel, ["push", "origin", "main"], logs, timeout=90.0)
    else:
        raise ValueError("No 'origin' git remote configured on repository.")

    sha = _run_git_checked(toplevel, ["rev-parse", "--short", "HEAD"], logs)
    return DeployResult(
        ok=True,
        target_env=target_env,
        commit_sha=sha,
        branch="main",
        remote_url=git_info.remote_url,
        pushed_files=chosen_rel_files,
        logs=logs,
    )
