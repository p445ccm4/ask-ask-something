from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

from .config import SKILL_SCRIPTS_DIR
from .workspaces import WorkspaceEntry


class UatRunRequest(BaseModel):
    case_ids: str = ""
    turn: int | None = None
    runs: int = 1
    limit: int | None = None
    no_eval: bool = False
    concurrency: int | None = None
    repo: Literal["dev", "uat"] = "dev"


class UatSummaryStats(BaseModel):
    total_cases: int = 0
    evaluated_cases: int = 0
    pass_count: int = 0
    partial_count: int = 0
    fail_count: int = 0
    total_score: float = 0.0
    score_pct: float = 0.0
    failing_ids: list[str] = Field(default_factory=list)


class UatOverview(BaseModel):
    workspace_id: str
    workspace_name: str
    repo: Literal["dev", "uat"] = "dev"
    has_config: bool = False
    has_questions: bool = False
    has_results: bool = False
    config: dict[str, Any] | None = None
    rubric_preview: str = ""
    questions_count: int = 0
    questions: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    result_files: list[str] = Field(default_factory=list)
    summary: UatSummaryStats = Field(default_factory=UatSummaryStats)
    results_updated_at: float | None = None


@dataclass
class UatJob:
    job_id: str
    workspace_id: str
    command: list[str]
    status: str = "running"  # running, completed, failed
    exit_code: int | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lines: list[str] = field(default_factory=list)
    _subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            q.put_nowait(event)


def compute_summary(results: list[dict[str, Any]]) -> UatSummaryStats:
    pass_cnt = 0
    partial_cnt = 0
    fail_cnt = 0
    total_score = 0.0
    failing_ids: list[str] = []

    for item in results:
        rev = item.get("uat_review") or {}
        status = str(rev.get("status") or "").upper()
        score = float(rev.get("score") or 0.0)
        total_score += score
        if status == "PASS":
            pass_cnt += 1
        elif status == "PARTIAL":
            partial_cnt += 1
            failing_ids.append(str(item.get("id", "")))
        elif status == "FAIL":
            fail_cnt += 1
            failing_ids.append(str(item.get("id", "")))

    evaluated = len(results)
    pct = round((total_score / evaluated) * 100, 1) if evaluated else 0.0
    return UatSummaryStats(
        total_cases=evaluated,
        evaluated_cases=evaluated,
        pass_count=pass_cnt,
        partial_count=partial_cnt,
        fail_count=fail_cnt,
        total_score=round(total_score, 2),
        score_pct=pct,
        failing_ids=[fid for fid in failing_ids if fid],
    )


class UatService:
    def __init__(self, scripts_dir: Path | None = None) -> None:
        self._scripts_dir = scripts_dir or SKILL_SCRIPTS_DIR
        self._jobs: dict[str, UatJob] = {}

    @property
    def run_batch_script(self) -> Path:
        return self._scripts_dir / "run_uat_batch.py"

    @property
    def xlsx_script(self) -> Path:
        return self._scripts_dir / "xlsx_to_uat.py"

    def _uat_paths(
        self,
        workspace: WorkspaceEntry,
        repo: Literal["dev", "uat"] = "dev",
    ) -> dict[str, Path]:
        if repo == "uat":
            raw_uat = (workspace.uat_path or "").strip()
            if not raw_uat:
                raise ValueError(
                    f"No paired UAT repository is configured for workspace '{workspace.name}'."
                )
            ws = Path(raw_uat).expanduser()
            if not ws.is_dir():
                raise FileNotFoundError(f"Paired UAT directory not found: {ws}")
        else:
            ws = Path(workspace.path)
        uat_dir = ws / "scripts" / "uat"
        dev_dir = ws / "scripts" / "dev"

        # Prefer canonical scripts/uat/ layout, fall back gracefully to legacy scripts/dev/ layout
        base_dir = uat_dir
        if not (uat_dir / "uat_questions.json").is_file() and (
            (dev_dir / "uat_questions_full.json").is_file()
            or (dev_dir / "uat_questions.json").is_file()
            or (dev_dir / "uat_results.json").is_file()
        ):
            base_dir = dev_dir

        cfg_path = base_dir / "uat_config.json"
        if not cfg_path.is_file() and (uat_dir / "uat_config.json").is_file():
            cfg_path = uat_dir / "uat_config.json"

        q_path = base_dir / "uat_questions.json"
        if not q_path.is_file() and (base_dir / "uat_questions_full.json").is_file():
            q_path = base_dir / "uat_questions_full.json"

        rubric_path = base_dir / "judge_rubric.md"
        if not rubric_path.is_file() and (uat_dir / "judge_rubric.md").is_file():
            rubric_path = uat_dir / "judge_rubric.md"

        results_dir = base_dir / "results" if (base_dir / "results").is_dir() else base_dir
        results_path = base_dir / "results" / "uat_results.json"
        if not results_path.is_file() and (base_dir / "uat_results.json").is_file():
            results_path = base_dir / "uat_results.json"
            results_dir = base_dir

        return {
            "ws": ws,
            "uat_dir": base_dir,
            "config": cfg_path,
            "questions": q_path,
            "rubric": rubric_path,
            "results_dir": results_dir,
            "results": results_path,
        }

    def get_overview(
        self,
        workspace: WorkspaceEntry,
        repo: Literal["dev", "uat"] = "dev",
    ) -> UatOverview:
        paths = self._uat_paths(workspace, repo=repo)
        cfg: dict[str, Any] | None = None
        if paths["config"].is_file():
            cfg = json.loads(paths["config"].read_text(encoding="utf-8"))

        rubric_text = ""
        if paths["rubric"].is_file():
            rubric_text = paths["rubric"].read_text(encoding="utf-8")
        elif cfg and (cfg.get("judge") or {}).get("rubric_file"):
            rf = Path(cfg["judge"]["rubric_file"])
            candidate = rf if rf.is_absolute() else (paths["uat_dir"] / rf)
            if candidate.is_file():
                rubric_text = candidate.read_text(encoding="utf-8")

        questions: list[dict[str, Any]] = []
        if paths["questions"].is_file():
            questions = json.loads(paths["questions"].read_text(encoding="utf-8"))

        results: list[dict[str, Any]] = []
        updated_at: float | None = None
        if paths["results"].is_file():
            results = json.loads(paths["results"].read_text(encoding="utf-8"))
            updated_at = paths["results"].stat().st_mtime

        result_files: list[str] = []
        if paths["results_dir"].is_dir():
            result_files = sorted(p.name for p in paths["results_dir"].iterdir() if p.is_file())

        summary = compute_summary(results)
        if not summary.total_cases and questions:
            summary.total_cases = len(questions)

        return UatOverview(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            repo=repo,
            has_config=paths["config"].is_file(),
            has_questions=paths["questions"].is_file(),
            has_results=paths["results"].is_file(),
            config=cfg,
            rubric_preview=rubric_text,
            questions_count=len(questions),
            questions=questions,
            results=results,
            result_files=result_files,
            summary=summary,
            results_updated_at=updated_at,
        )

    def get_case_detail(
        self,
        workspace: WorkspaceEntry,
        case_id: str,
        repo: Literal["dev", "uat"] = "dev",
    ) -> dict[str, Any]:
        overview = self.get_overview(workspace, repo=repo)
        target_id = case_id.strip()
        for item in overview.results:
            if str(item.get("id", "")).lower() == target_id.lower():
                return {"found_in": "uat_results.json", "repo": repo, "case": item}
        for q in overview.questions:
            if str(q.get("id", "")).lower() == target_id.lower():
                return {"found_in": "uat_questions.json", "repo": repo, "case": q}
        raise KeyError(
            f"UAT case '{case_id}' not found in {repo.upper()} repo of workspace '{workspace.name}'."
        )

    def build_run_command(self, workspace: WorkspaceEntry, req: UatRunRequest) -> tuple[list[str], Path]:
        paths = self._uat_paths(workspace, repo=req.repo)
        if not paths["config"].is_file():
            raise FileNotFoundError(f"Missing uat_config.json at {paths['config']}")
        if not paths["questions"].is_file():
            raise FileNotFoundError(f"Missing uat_questions.json at {paths['questions']}")

        output_path = paths["results"]
        if req.case_ids.strip():
            safe_slug = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in req.case_ids.strip())[:40]
            output_path = paths["results_dir"] / f"targeted_{safe_slug}.json"

        cmd = [
            sys.executable,
            "-u",
            str(self.run_batch_script),
            "--config",
            str(paths["config"]),
            "-i",
            str(paths["questions"]),
            "-o",
            str(output_path),
        ]
        if req.case_ids.strip():
            cmd.extend(["--id", req.case_ids.strip()])
        if req.turn is not None:
            cmd.extend(["--turn", str(req.turn)])
            if paths["results"].is_file():
                cmd.extend(["--from-results", str(paths["results"])])
        if req.runs > 1:
            cmd.extend(["--runs", str(req.runs)])
        if req.limit is not None and req.limit > 0:
            cmd.extend(["--limit", str(req.limit)])
        if req.concurrency is not None and req.concurrency > 0:
            cmd.extend(["--concurrency", str(req.concurrency)])
        if req.no_eval:
            cmd.append("--no-eval")

        return cmd, output_path

    async def start_run_job(self, workspace: WorkspaceEntry, req: UatRunRequest) -> UatJob:
        paths = self._uat_paths(workspace, repo=req.repo)
        cmd, output_path = self.build_run_command(workspace, req)
        job_id = f"uat_{uuid4().hex[:10]}"
        job = UatJob(job_id=job_id, workspace_id=workspace.id, command=cmd)
        self._jobs[job_id] = job
        asyncio.create_task(self._execute_job(job, paths["ws"], output_path))
        return job

    async def _execute_job(self, job: UatJob, cwd: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                *job.command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                job.lines.append(line)
                job.publish({"type": "log", "line": line})

            rc = await proc.wait()
            job.exit_code = rc
            job.status = "completed" if rc == 0 else "failed"
            job.finished_at = time.time()
            job.publish(
                {
                    "type": "done",
                    "status": job.status,
                    "exit_code": rc,
                    "output_file": str(output_path),
                }
            )
        except Exception as exc:  # pragma: no cover
            job.status = "failed"
            job.exit_code = -1
            job.finished_at = time.time()
            err_line = f"ERROR: {exc}"
            job.lines.append(err_line)
            job.publish({"type": "log", "line": err_line})
            job.publish({"type": "done", "status": "failed", "exit_code": -1})

    def get_job(self, job_id: str) -> UatJob:
        if job_id not in self._jobs:
            raise KeyError(f"UAT job not found: {job_id}")
        return self._jobs[job_id]

    async def stream_job(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        job = self.get_job(job_id)
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        job._subscribers.add(q)
        try:
            for line in list(job.lines):
                yield {"type": "log", "line": line}
            if job.status != "running":
                yield {"type": "done", "status": job.status, "exit_code": job.exit_code}
                return
            while True:
                ev = await q.get()
                yield ev
                if ev.get("type") == "done":
                    break
        finally:
            job._subscribers.discard(q)

    async def run_and_collect(self, workspace: WorkspaceEntry, req: UatRunRequest) -> dict[str, Any]:
        paths = self._uat_paths(workspace, repo=req.repo)
        cmd, output_path = self.build_run_command(workspace, req)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(paths["ws"]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout_bytes, _ = await proc.communicate()
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        results: list[dict[str, Any]] = []
        if output_path.is_file():
            results = json.loads(output_path.read_text(encoding="utf-8"))
        summary = compute_summary(results)
        return {
            "repo": req.repo,
            "exit_code": proc.returncode,
            "output_file": str(output_path),
            "summary": summary.model_dump(),
            "results": results,
            "logs_tail": "\n".join(stdout_text.splitlines()[-60:]),
        }

    async def export_csv(
        self,
        workspace: WorkspaceEntry,
        repo: Literal["dev", "uat"] = "dev",
    ) -> Path:
        paths = self._uat_paths(workspace, repo=repo)
        if not paths["results"].is_file():
            raise FileNotFoundError(f"No uat_results.json found at {paths['results']}")
        csv_out = paths["results_dir"] / "uat_results.csv"
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.xlsx_script),
            "export",
            str(paths["results"]),
            "-o",
            str(csv_out),
            cwd=str(paths["ws"]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out_bytes, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"CSV export failed: {out_bytes.decode('utf-8', errors='replace')}")
        return csv_out
