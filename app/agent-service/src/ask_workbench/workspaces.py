from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


class WorkspaceEntry(BaseModel):
    id: str
    name: str
    path: str
    uat_path: str | None = None
    env: str = "dev"


class GitChangedFile(BaseModel):
    status: str
    path: str  # Relative to workspace service root


class WorkspaceGitInfo(BaseModel):
    is_git_repo: bool = False
    git_toplevel: str | None = None
    service_subpath: str = "."
    branch: str | None = None
    remote_url: str | None = None
    changed_files: list[GitChangedFile] = Field(default_factory=list)
    unpushed_commits: list[str] = Field(default_factory=list)
    diff: str = ""


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    path: str
    uat_path: str | None = None
    uat_exists: bool = False
    env: str = "dev"
    exists: bool = True
    has_uat_config: bool = False
    has_uat_questions: bool = False
    has_uat_results: bool = False
    branch: str | None = None
    dirty_count: int = 0
    unpushed_count: int = 0


_TRANSIENT_PREFIXES = (
    "scripts/uat/results/",
    "scripts/dev/uat_results",
    "scripts/dev/__pycache__/",
    ".venv/",
    "venv/",
    "__pycache__/",
    "node_modules/",
    ".next/",
)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workspace"


def _run_git(cwd: Path, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def is_transient_service_relpath(rel_path: str) -> bool:
    norm = rel_path.strip().lstrip("./")
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


class WorkspaceRegistry:
    def __init__(
        self,
        registry_file: Path,
        seed_defaults: bool = True,
        default_workspaces_json: str = "",
    ) -> None:
        self._file = registry_file
        self._seed_defaults = seed_defaults
        self._default_workspaces_json = default_workspaces_json
        self._ensure_initialized()

    def _default_candidates(self) -> list[WorkspaceEntry]:
        raw_cfg = (self._default_workspaces_json or "").strip()
        if not raw_cfg:
            return []
        try:
            items = json.loads(raw_cfg)
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []

        entries: list[WorkspaceEntry] = []
        used_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            resolved = Path(str(item["path"])).expanduser()
            if not resolved.is_dir():
                continue
            name = str(item.get("name") or resolved.name).strip()
            ws_id = str(item.get("id") or _slugify(name)).strip()
            while ws_id in used_ids:
                ws_id = f"{ws_id}-2"
            used_ids.add(ws_id)
            uat_raw = item.get("uat_path")
            uat_str = str(Path(str(uat_raw)).expanduser()) if uat_raw else None
            entries.append(
                WorkspaceEntry(
                    id=ws_id,
                    name=name,
                    path=str(resolved),
                    uat_path=uat_str,
                    env=str(item.get("env") or "dev"),
                )
            )
        return entries

    def _ensure_initialized(self) -> None:
        if self._file.is_file():
            return
        self._file.parent.mkdir(parents=True, exist_ok=True)
        initial = self._default_candidates() if self._seed_defaults else []
        self._save(initial)

    def _load(self) -> list[WorkspaceEntry]:
        if not self._file.is_file():
            return []
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        return [WorkspaceEntry.model_validate(item) for item in raw]

    def _save(self, entries: list[WorkspaceEntry]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = [e.model_dump() for e in entries]
        self._file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_entries(self) -> list[WorkspaceEntry]:
        return self._load()

    def get_entry(self, ws_id: str) -> WorkspaceEntry:
        for entry in self._load():
            if entry.id == ws_id:
                return entry
        raise KeyError(f"Workspace not found: {ws_id}")

    def add_entry(
        self,
        name: str,
        path: str,
        uat_path: str | None = None,
        env: str = "dev",
    ) -> WorkspaceEntry:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Directory does not exist: {resolved}")

        uat_resolved_str: str | None = None
        if uat_path and uat_path.strip():
            uat_p = Path(uat_path).expanduser().resolve()
            if not uat_p.is_dir():
                raise ValueError(f"UAT directory does not exist: {uat_p}")
            uat_resolved_str = str(uat_p)

        entries = self._load()
        for existing in entries:
            if Path(existing.path).resolve() == resolved:
                return existing

        base_id = _slugify(name or resolved.name)
        existing_ids = {e.id for e in entries}
        ws_id = base_id
        counter = 2
        while ws_id in existing_ids:
            ws_id = f"{base_id}-{counter}"
            counter += 1

        new_entry = WorkspaceEntry(
            id=ws_id,
            name=name.strip() or resolved.name,
            path=str(resolved),
            uat_path=uat_resolved_str,
            env=env,
        )
        entries.append(new_entry)
        self._save(entries)
        return new_entry

    def summarize(self, entry: WorkspaceEntry) -> WorkspaceSummary:
        p = Path(entry.path)
        exists = p.is_dir()
        uat_dir = p / "scripts" / "uat"
        dev_dir = p / "scripts" / "dev"
        has_cfg = (uat_dir / "uat_config.json").is_file() or (dev_dir / "uat_config.json").is_file()
        has_q = (
            (uat_dir / "uat_questions.json").is_file()
            or (dev_dir / "uat_questions.json").is_file()
            or (dev_dir / "uat_questions_full.json").is_file()
        )
        has_res = (
            (uat_dir / "results" / "uat_results.json").is_file()
            or (dev_dir / "uat_results.json").is_file()
            or (dev_dir / "results" / "uat_results.json").is_file()
        )
        git_info = inspect_workspace_git(p) if exists else WorkspaceGitInfo()
        uat_exists = bool(entry.uat_path and Path(entry.uat_path).is_dir())
        return WorkspaceSummary(
            id=entry.id,
            name=entry.name,
            path=entry.path,
            uat_path=entry.uat_path,
            uat_exists=uat_exists,
            env=entry.env,
            exists=exists,
            has_uat_config=has_cfg,
            has_uat_questions=has_q,
            has_uat_results=has_res,
            branch=git_info.branch,
            dirty_count=len(git_info.changed_files),
            unpushed_count=len(git_info.unpushed_commits),
        )

    def list_summaries(self) -> list[WorkspaceSummary]:
        return [self.summarize(e) for e in self._load()]


def summarize_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    raise TypeError(f"Unsupported type: {type(obj)}")
