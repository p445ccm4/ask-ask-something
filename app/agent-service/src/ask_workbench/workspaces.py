from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from ag_workbench.artifacts import AG_ARTIFACTS_DIR_NAME
from pydantic import BaseModel, Field

from .ask_workbench_db import VALID_ENVS, AskWorkbenchDB, EnvName, slugify_id


class WorkspaceEntry(BaseModel):
    """Legacy/single-workspace compatibility representation convertible to ProjectEntry."""

    id: str
    name: str
    path: str
    uat_path: str | None = None
    env: str = "dev"

    def to_project_entry(self) -> ProjectEntry:
        envs: dict[str, str] = {}
        active: EnvName = self.env if self.env in VALID_ENVS else "dev"  # type: ignore[assignment]
        if self.path and self.path.strip():
            envs[active] = self.path.strip()
        if self.uat_path and self.uat_path.strip() and "uat" not in envs:
            envs["uat"] = self.uat_path.strip()
        return ProjectEntry(
            id=self.id,
            name=self.name,
            active_env=active,
            environments=envs,
        )


class ProjectEntry(BaseModel):
    id: str
    name: str
    active_env: EnvName = "dev"
    environments: dict[str, str] = Field(default_factory=dict)

    @property
    def path(self) -> str:
        if self.active_env in self.environments:
            return self.environments[self.active_env]
        for env in VALID_ENVS:
            if env in self.environments:
                return self.environments[env]
        return ""

    @property
    def uat_path(self) -> str | None:
        return self.environments.get("uat")

    @property
    def configured_envs(self) -> list[EnvName]:
        return [e for e in VALID_ENVS if e in self.environments and self.environments[e].strip()]

    def path_for_env(self, env: str | None = None) -> str:
        target = env or self.active_env
        if target in self.environments and self.environments[target].strip():
            return self.environments[target]
        raise ValueError(f"Environment '{target}' is not configured on project '{self.name}'.")


class GitChangedFile(BaseModel):
    status: str
    path: str  # Relative to service root


class WorkspaceGitInfo(BaseModel):
    is_git_repo: bool = False
    git_toplevel: str | None = None
    service_subpath: str = "."
    branch: str | None = None
    remote_url: str | None = None
    changed_files: list[GitChangedFile] = Field(default_factory=list)
    unpushed_commits: list[str] = Field(default_factory=list)
    diff: str = ""


class EnvGitSummary(BaseModel):
    env: EnvName
    path: str
    exists: bool = False
    branch: str | None = None
    dirty_count: int = 0
    unpushed_count: int = 0
    remote_url: str | None = None


class EnvEvalBrief(BaseModel):
    suite_count: int = 0
    default_suite_id: str | None = None
    default_suite_name: str | None = None
    endpoint: str | None = None
    total_cases: int = 0
    evaluated_cases: int = 0
    pass_count: int = 0
    partial_count: int = 0
    fail_count: int = 0
    score_pct: float = 0.0


class ProjectSummary(BaseModel):
    id: str
    name: str
    active_env: EnvName = "dev"
    path: str
    exists: bool = True
    environments: dict[str, str] = Field(default_factory=dict)
    configured_envs: list[EnvName] = Field(default_factory=list)
    env_git: dict[str, EnvGitSummary] = Field(default_factory=dict)
    env_eval: dict[str, EnvEvalBrief] = Field(default_factory=dict)
    branch: str | None = None
    dirty_count: int = 0
    unpushed_count: int = 0


_TRANSIENT_PREFIXES = (
    f"{AG_ARTIFACTS_DIR_NAME}/",
    "scripts/uat/results/",
    "scripts/dev/uat_results",
    "scripts/dev/__pycache__/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "node_modules/",
    ".next/",
)


def _run_git(cwd: Path, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def normalize_service_relpath(rel_path: str) -> str:
    norm = rel_path.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def is_transient_service_relpath(rel_path: str) -> bool:
    norm = normalize_service_relpath(rel_path)
    if norm == AG_ARTIFACTS_DIR_NAME:
        return True
    if any(norm.startswith(p) or f"/{p}" in norm for p in _TRANSIENT_PREFIXES):
        return True
    if norm.endswith((".pyc", ".pyo", ".DS_Store")):
        return True
    return False


def inspect_workspace_git(ws_path: Path) -> WorkspaceGitInfo:
    if not ws_path.is_dir():
        return WorkspaceGitInfo()

    top_res = _run_git(ws_path, ["rev-parse", "--show-toplevel"])
    if top_res.returncode != 0:
        return WorkspaceGitInfo()

    toplevel = Path(top_res.stdout.strip()).resolve()
    ws_resolved = ws_path.resolve()
    try:
        sub = ws_resolved.relative_to(toplevel)
        sub_str = "." if str(sub) == "." else sub.as_posix()
    except ValueError:
        sub_str = "."

    branch_res = _run_git(toplevel, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_res.stdout.strip() if branch_res.returncode == 0 else None

    remote_res = _run_git(toplevel, ["remote", "get-url", "origin"])
    remote_url = remote_res.stdout.strip() if remote_res.returncode == 0 else None

    status_args = ["status", "--porcelain", "-uall"]
    if sub_str != ".":
        status_args.extend(["--", sub_str])
    st_res = _run_git(toplevel, status_args)

    changed: list[GitChangedFile] = []
    untracked_rel_to_ws: list[str] = []
    if st_res.returncode == 0:
        prefix = "" if sub_str == "." else f"{sub_str}/"
        for line in st_res.stdout.splitlines():
            if len(line) < 4:
                continue
            code = line[:2].strip() or "M"
            raw_path = line[3:].strip().strip('"')
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ", 1)[1].strip('"')
            rel_ws = raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path
            if is_transient_service_relpath(rel_ws):
                continue
            changed.append(GitChangedFile(status=code, path=rel_ws))
            if code == "??":
                untracked_rel_to_ws.append(rel_ws)

    unpushed: list[str] = []
    if branch:
        log_args = ["log", f"origin/{branch}..HEAD", "--oneline"]
        if sub_str != ".":
            log_args.extend(["--", sub_str])
        log_res = _run_git(toplevel, log_args)
        if log_res.returncode == 0:
            unpushed = [ln.strip() for ln in log_res.stdout.splitlines() if ln.strip()]

    diff_args = ["diff", "HEAD"]
    if sub_str != ".":
        diff_args.extend(["--", sub_str])
    diff_res = _run_git(toplevel, diff_args)
    diff_parts: list[str] = []
    if diff_res.returncode == 0 and diff_res.stdout.strip():
        diff_parts.append(diff_res.stdout.rstrip())

    for untracked in untracked_rel_to_ws[:15]:
        full_file = ws_resolved / untracked
        if full_file.is_file() and full_file.stat().st_size <= 100_000:
            try:
                content = full_file.read_text(encoding="utf-8", errors="replace")
                added_lines = "\n".join(f"+{ln}" for ln in content.splitlines())
                label_path = untracked if sub_str == "." else f"{sub_str}/{untracked}"
                diff_parts.append(
                    f"diff --git a/{label_path} b/{label_path}\n"
                    f"new file mode 100644\n"
                    f"--- /dev/null\n"
                    f"+++ b/{label_path}\n"
                    f"@@ -0,0 +1,{max(1, len(content.splitlines()))} @@\n"
                    f"{added_lines}"
                )
            except OSError:
                pass

    return WorkspaceGitInfo(
        is_git_repo=True,
        git_toplevel=str(toplevel),
        service_subpath=sub_str,
        branch=branch,
        remote_url=remote_url,
        changed_files=changed,
        unpushed_commits=unpushed,
        diff="\n\n".join(diff_parts),
    )


class ProjectRegistry:
    """SQLite-backed Project & Multi-Environment Registry (replaces legacy workspaces.json)."""

    def __init__(
        self,
        db: AskWorkbenchDB,
        *,
        legacy_registry_file: Path | None = None,
        seed_defaults: bool = True,
        default_workspaces_json: str = "",
    ) -> None:
        self._db = db
        self._legacy_file = legacy_registry_file
        self._seed_defaults = seed_defaults
        self._default_workspaces_json = default_workspaces_json
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        if self._db.count_projects() > 0:
            return

        if self._legacy_file and self._legacy_file.is_file():
            try:
                raw_items = json.loads(self._legacy_file.read_text(encoding="utf-8"))
                if isinstance(raw_items, list):
                    for item in raw_items:
                        self._seed_item(item)
                    if self._db.count_projects() > 0:
                        return
            except (OSError, json.JSONDecodeError):
                pass

        if self._seed_defaults and (self._default_workspaces_json or "").strip():
            try:
                items = json.loads(self._default_workspaces_json)
                if isinstance(items, list):
                    for item in items:
                        self._seed_item(item)
            except json.JSONDecodeError:
                pass

    def _seed_item(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        envs: dict[str, str] = {}
        if isinstance(item.get("environments"), dict):
            for env in VALID_ENVS:
                val = item["environments"].get(env)
                if val and str(val).strip():
                    p = Path(str(val)).expanduser()
                    if p.is_dir():
                        envs[env] = str(p.resolve())
        elif item.get("path"):
            p = Path(str(item["path"])).expanduser()
            env_key = str(item.get("env") or "dev").lower()
            if env_key not in VALID_ENVS:
                env_key = "dev"
            if p.is_dir():
                envs[env_key] = str(p.resolve())
            if item.get("uat_path"):
                up = Path(str(item["uat_path"])).expanduser()
                if up.is_dir():
                    envs["uat"] = str(up.resolve())

        if not envs:
            return

        name = str(item.get("name") or next(iter(envs.values()))).strip()
        pid = str(item.get("id") or slugify_id(name, "project")).strip()
        active_env = str(item.get("active_env") or item.get("env") or "dev").lower()
        if active_env not in envs:
            active_env = "dev" if "dev" in envs else next(iter(envs.keys()))
        try:
            self._db.create_project(
                name=name,
                environments=envs,
                project_id=pid,
                active_env=active_env,
            )
        except ValueError:
            pass

    @staticmethod
    def _row_to_entry(row: dict[str, Any]) -> ProjectEntry:
        return ProjectEntry(
            id=row["id"],
            name=row["name"],
            active_env=row["active_env"],
            environments=row["environments"],
        )

    def _validate_env_paths(
        self, environments: dict[str, str | None]
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for env in VALID_ENVS:
            raw = environments.get(env)
            if raw is None or not str(raw).strip():
                continue
            p = Path(str(raw)).expanduser().resolve()
            if not p.is_dir():
                raise ValueError(f"{env.upper()} directory does not exist: {p}")
            resolved[env] = str(p)
        return resolved

    def list_entries(self) -> list[ProjectEntry]:
        return [self._row_to_entry(r) for r in self._db.list_projects()]

    def get_entry(self, project_id: str) -> ProjectEntry:
        return self._row_to_entry(self._db.get_project(project_id))

    def all_registered_paths(self) -> set[Path]:
        paths: set[Path] = set()
        for entry in self.list_entries():
            for p_str in entry.environments.values():
                if p_str.strip():
                    paths.add(Path(p_str).expanduser().resolve())
        return paths

    def add_project(
        self,
        name: str,
        environments: dict[str, str | None],
        *,
        active_env: str | None = None,
        project_id: str | None = None,
    ) -> ProjectEntry:
        clean_envs = self._validate_env_paths(environments)
        if not clean_envs:
            raise ValueError(
                "At least one environment repository path (SBX, DEV, UAT, or PROD) is required."
            )

        # If an existing project has the exact same set of configured paths, return/merge cleanly
        for existing in self.list_entries():
            if existing.environments == clean_envs:
                return existing

        chosen_active = active_env if active_env in clean_envs else None
        if not chosen_active:
            chosen_active = "dev" if "dev" in clean_envs else next(
                e for e in VALID_ENVS if e in clean_envs
            )
        fallback_name = name.strip() or Path(clean_envs[chosen_active]).name
        created = self._db.create_project(
            name=fallback_name,
            environments=clean_envs,
            project_id=project_id,
            active_env=chosen_active,
        )
        return self._row_to_entry(created)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        environments: dict[str, str | None] | None = None,
        active_env: str | None = None,
    ) -> ProjectEntry:
        validated_envs: dict[str, str | None] | None = None
        if environments is not None:
            validated_envs = {}
            for env in VALID_ENVS:
                if env not in environments:
                    continue
                raw = environments[env]
                if raw is None or not str(raw).strip():
                    validated_envs[env] = ""
                else:
                    p = Path(str(raw)).expanduser().resolve()
                    if not p.is_dir():
                        raise ValueError(f"{env.upper()} directory does not exist: {p}")
                    validated_envs[env] = str(p)

        updated = self._db.update_project(
            project_id,
            name=name,
            environments=validated_envs,
            active_env=active_env,
        )
        return self._row_to_entry(updated)

    def delete_project(self, project_id: str) -> bool:
        return self._db.delete_project(project_id)

    def summarize(self, entry: ProjectEntry) -> ProjectSummary:
        env_git: dict[str, EnvGitSummary] = {}
        env_eval: dict[str, EnvEvalBrief] = {}

        for env in VALID_ENVS:
            raw_path = entry.environments.get(env)
            if not raw_path or not raw_path.strip():
                continue
            p = Path(raw_path)
            exists = p.is_dir()
            git_info = inspect_workspace_git(p) if exists else WorkspaceGitInfo()
            env_git[env] = EnvGitSummary(
                env=env,
                path=raw_path,
                exists=exists,
                branch=git_info.branch,
                dirty_count=len(git_info.changed_files),
                unpushed_count=len(git_info.unpushed_commits),
                remote_url=git_info.remote_url,
            )

            suites_page = self._db.list_suites(entry.id, env, limit=1, offset=0)
            suite_count = int(suites_page["total"])
            if suites_page["suites"]:
                top = suites_page["suites"][0]
                env_eval[env] = EnvEvalBrief(
                    suite_count=suite_count,
                    default_suite_id=top["id"],
                    default_suite_name=top["name"],
                    endpoint=top.get("endpoint") or None,
                    total_cases=top["total_cases"],
                    evaluated_cases=top["evaluated_cases"],
                    pass_count=top["pass_count"],
                    partial_count=top["partial_count"],
                    fail_count=top["fail_count"],
                    score_pct=top["score_pct"],
                )
            else:
                env_eval[env] = EnvEvalBrief(suite_count=0)

        active_git = env_git.get(entry.active_env)
        active_path = entry.path
        return ProjectSummary(
            id=entry.id,
            name=entry.name,
            active_env=entry.active_env,
            path=active_path,
            exists=bool(active_git.exists) if active_git else Path(active_path).is_dir(),
            environments=dict(entry.environments),
            configured_envs=entry.configured_envs,
            env_git=env_git,
            env_eval=env_eval,
            branch=active_git.branch if active_git else None,
            dirty_count=active_git.dirty_count if active_git else 0,
            unpushed_count=active_git.unpushed_count if active_git else 0,
        )

    def list_summaries(self) -> list[ProjectSummary]:
        return [self.summarize(e) for e in self.list_entries()]
