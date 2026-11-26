from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

EnvName = Literal["sbx", "dev", "uat", "prod"]
VALID_ENVS: tuple[EnvName, ...] = ("sbx", "dev", "uat", "prod")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_id(text: str, fallback: str = "item") -> str:
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return slug or fallback


def normalize_turns(raw_item: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize single-turn or multi-turn question payload into canonical turns list."""
    raw_turns = raw_item.get("turns")
    out: list[dict[str, str]] = []
    if isinstance(raw_turns, list):
        for t in raw_turns:
            if not isinstance(t, dict):
                continue
            q = str(t.get("question") or "").strip()
            if not q:
                continue
            out.append(
                {
                    "question": q,
                    "expected_answer": str(t.get("expected_answer") or ""),
                    "expected_behavior": str(t.get("expected_behavior") or ""),
                }
            )
        return out

    q = str(raw_item.get("question") or "").strip()
    if q:
        out.append(
            {
                "question": q,
                "expected_answer": str(raw_item.get("expected_answer") or ""),
                "expected_behavior": str(raw_item.get("expected_behavior") or ""),
            }
        )
    return out


class AskWorkbenchDB:
    """Thread-safe SQLite WAL single-source-of-truth store for Projects and Eval Suites."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=5000;")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    active_env TEXT NOT NULL DEFAULT 'dev' CHECK(active_env IN ('sbx','dev','uat','prod')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_environments (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    env TEXT NOT NULL CHECK(env IN ('sbx','dev','uat','prod')),
                    repo_path TEXT NOT NULL,
                    PRIMARY KEY (project_id, env)
                );

                CREATE TABLE IF NOT EXISTS eval_suites (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    env TEXT NOT NULL CHECK(env IN ('sbx','dev','uat','prod')),
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    rubric_md TEXT NOT NULL DEFAULT '',
                    excel_mapping_json TEXT NOT NULL DEFAULT '{}',
                    source_xlsx_name TEXT NOT NULL DEFAULT '',
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(project_id, env, slug)
                );
                CREATE INDEX IF NOT EXISTS idx_eval_suites_proj_env
                    ON eval_suites(project_id, env, is_default DESC, updated_at DESC);

                CREATE TABLE IF NOT EXISTS eval_cases (
                    suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
                    case_id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    first_question TEXT NOT NULL DEFAULT '',
                    turn_count INTEGER NOT NULL DEFAULT 1,
                    turns_json TEXT NOT NULL DEFAULT '[]',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (suite_id, case_id)
                );
                CREATE INDEX IF NOT EXISTS idx_eval_cases_order
                    ON eval_cases(suite_id, sort_order, case_id);

                CREATE TABLE IF NOT EXISTS eval_runs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    env TEXT NOT NULL CHECK(env IN ('sbx','dev','uat','prod')),
                    suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'running',
                    exit_code INTEGER,
                    endpoint TEXT NOT NULL DEFAULT '',
                    command_json TEXT NOT NULL DEFAULT '[]',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    started_at REAL NOT NULL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_eval_runs_suite
                    ON eval_runs(suite_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS eval_run_results (
                    job_id TEXT NOT NULL REFERENCES eval_runs(job_id) ON DELETE CASCADE,
                    suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
                    case_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    score REAL NOT NULL DEFAULT 0.0,
                    comment TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (job_id, case_id)
                );

                CREATE TABLE IF NOT EXISTS eval_latest_results (
                    suite_id TEXT NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
                    case_id TEXT NOT NULL,
                    job_id TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    score REAL NOT NULL DEFAULT 0.0,
                    comment TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (suite_id, case_id)
                );
                CREATE INDEX IF NOT EXISTS idx_eval_latest_status
                    ON eval_latest_results(suite_id, status, case_id);

                CREATE TABLE IF NOT EXISTS eval_run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES eval_runs(job_id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    line TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eval_run_logs_job_seq
                    ON eval_run_logs(job_id, seq);
                """
            )

    # ------------------------------------------------------------------
    # Projects & Environments
    # ------------------------------------------------------------------
    def count_projects(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM projects").fetchone()
            return int(row["cnt"]) if row else 0

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            proj_rows = conn.execute(
                "SELECT id, name, active_env, created_at, updated_at FROM projects ORDER BY created_at ASC, name ASC"
            ).fetchall()
            env_rows = conn.execute(
                "SELECT project_id, env, repo_path FROM project_environments"
            ).fetchall()
            env_map: dict[str, dict[str, str]] = {}
            for er in env_rows:
                env_map.setdefault(er["project_id"], {})[er["env"]] = er["repo_path"]

            out: list[dict[str, Any]] = []
            for pr in proj_rows:
                envs = env_map.get(pr["id"], {})
                active_env = pr["active_env"]
                if active_env not in envs and envs:
                    active_env = next((e for e in VALID_ENVS if e in envs), next(iter(envs)))
                out.append(
                    {
                        "id": pr["id"],
                        "name": pr["name"],
                        "active_env": active_env,
                        "environments": {e: envs[e] for e in VALID_ENVS if e in envs},
                        "created_at": pr["created_at"],
                        "updated_at": pr["updated_at"],
                    }
                )
            return out

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            pr = conn.execute(
                "SELECT id, name, active_env, created_at, updated_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if not pr:
                raise KeyError(f"Project not found: {project_id}")
            env_rows = conn.execute(
                "SELECT env, repo_path FROM project_environments WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            envs = {er["env"]: er["repo_path"] for er in env_rows}
            active_env = pr["active_env"]
            if active_env not in envs and envs:
                active_env = next((e for e in VALID_ENVS if e in envs), next(iter(envs)))
            return {
                "id": pr["id"],
                "name": pr["name"],
                "active_env": active_env,
                "environments": {e: envs[e] for e in VALID_ENVS if e in envs},
                "created_at": pr["created_at"],
                "updated_at": pr["updated_at"],
            }

    def create_project(
        self,
        name: str,
        environments: dict[str, str],
        *,
        project_id: str | None = None,
        active_env: str | None = None,
    ) -> dict[str, Any]:
        clean_envs = {
            e: str(environments[e]).strip()
            for e in VALID_ENVS
            if e in environments and str(environments[e] or "").strip()
        }
        if not clean_envs:
            raise ValueError("At least one environment repository path (sbx, dev, uat, or prod) must be provided.")

        chosen_env = active_env if active_env in clean_envs else None
        if not chosen_env:
            chosen_env = "dev" if "dev" in clean_envs else next(e for e in VALID_ENVS if e in clean_envs)

        now = time.time()
        with self._connect() as conn:
            existing_ids = {
                r["id"] for r in conn.execute("SELECT id FROM projects").fetchall()
            }
            base_id = slugify_id(project_id or name, fallback="project")
            final_id = base_id
            suffix = 2
            while final_id in existing_ids:
                final_id = f"{base_id}-{suffix}"
                suffix += 1

            conn.execute(
                "INSERT INTO projects(id, name, active_env, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (final_id, name.strip() or final_id, chosen_env, now, now),
            )
            for env, repo_path in clean_envs.items():
                conn.execute(
                    "INSERT INTO project_environments(project_id, env, repo_path) VALUES (?, ?, ?)",
                    (final_id, env, repo_path),
                )
        return self.get_project(final_id)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        environments: dict[str, str | None] | None = None,
        active_env: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_project(project_id)
        next_name = name.strip() if isinstance(name, str) and name.strip() else current["name"]

        next_envs = dict(current["environments"])
        if environments is not None:
            rebuilt: dict[str, str] = {}
            for env in VALID_ENVS:
                if env in environments:
                    val = str(environments[env] or "").strip()
                    if val:
                        rebuilt[env] = val
                elif env in next_envs:
                    rebuilt[env] = next_envs[env]
            next_envs = rebuilt
        if not next_envs:
            raise ValueError("At least one environment repository path must remain configured.")

        next_active = current["active_env"]
        if active_env is not None:
            if active_env not in next_envs:
                raise ValueError(f"Environment '{active_env}' is not configured on project '{next_name}'.")
            next_active = active_env
        elif next_active not in next_envs:
            next_active = "dev" if "dev" in next_envs else next(e for e in VALID_ENVS if e in next_envs)

        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET name = ?, active_env = ?, updated_at = ? WHERE id = ?",
                (next_name, next_active, now, project_id),
            )
            if environments is not None:
                conn.execute(
                    "DELETE FROM project_environments WHERE project_id = ?",
                    (project_id,),
                )
                for env, repo_path in next_envs.items():
                    conn.execute(
                        "INSERT INTO project_environments(project_id, env, repo_path) VALUES (?, ?, ?)",
                        (project_id, env, repo_path),
                    )
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Eval Suites
    # ------------------------------------------------------------------
    def _suite_id_for(self, project_id: str, env: str, slug: str) -> str:
        return f"{project_id}__{env}__{slug}"

    def list_suites(
        self,
        project_id: str,
        env: EnvName,
        *,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = f"%{search.strip().lower()}%" if search.strip() else ""
        with self._connect() as conn:
            where = "s.project_id = ? AND s.env = ?"
            params: list[Any] = [project_id, env]
            if q:
                where += " AND (LOWER(s.name) LIKE ? OR LOWER(s.slug) LIKE ? OR LOWER(s.description) LIKE ?)"
                params.extend([q, q, q])

            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM eval_suites s WHERE {where}",
                tuple(params),
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0

            rows = conn.execute(
                f"""
                SELECT
                    s.id, s.project_id, s.env, s.slug, s.name, s.description,
                    s.config_json, s.source_xlsx_name, s.is_default, s.created_at, s.updated_at,
                    (SELECT COUNT(*) FROM eval_cases c WHERE c.suite_id = s.id) AS total_cases,
                    (SELECT COUNT(*) FROM eval_latest_results r WHERE r.suite_id = s.id AND r.status IN ('PASS','PARTIAL','FAIL')) AS evaluated_cases,
                    (SELECT COUNT(*) FROM eval_latest_results r WHERE r.suite_id = s.id AND r.status = 'PASS') AS pass_count,
                    (SELECT COUNT(*) FROM eval_latest_results r WHERE r.suite_id = s.id AND r.status = 'PARTIAL') AS partial_count,
                    (SELECT COUNT(*) FROM eval_latest_results r WHERE r.suite_id = s.id AND r.status = 'FAIL') AS fail_count,
                    (SELECT COALESCE(SUM(r.score), 0.0) FROM eval_latest_results r WHERE r.suite_id = s.id AND r.status IN ('PASS','PARTIAL','FAIL')) AS total_score,
                    (SELECT MAX(r.updated_at) FROM eval_latest_results r WHERE r.suite_id = s.id) AS last_eval_at
                FROM eval_suites s
                WHERE {where}
                ORDER BY s.is_default DESC, s.updated_at DESC, s.name ASC
                LIMIT ? OFFSET ?
                """,
                tuple([*params, max(1, min(limit, 500)), max(0, offset)]),
            ).fetchall()

            suites: list[dict[str, Any]] = []
            for row in rows:
                cfg = self._safe_json_obj(row["config_json"])
                eval_cnt = int(row["evaluated_cases"] or 0)
                t_score = float(row["total_score"] or 0.0)
                pct = round((t_score / eval_cnt) * 100.0, 1) if eval_cnt else 0.0
                suites.append(
                    {
                        "id": row["id"],
                        "project_id": row["project_id"],
                        "env": row["env"],
                        "slug": row["slug"],
                        "name": row["name"],
                        "description": row["description"],
                        "endpoint": str(cfg.get("endpoint") or ""),
                        "source_xlsx_name": row["source_xlsx_name"],
                        "is_default": bool(row["is_default"]),
                        "total_cases": int(row["total_cases"] or 0),
                        "evaluated_cases": eval_cnt,
                        "pass_count": int(row["pass_count"] or 0),
                        "partial_count": int(row["partial_count"] or 0),
                        "fail_count": int(row["fail_count"] or 0),
                        "total_score": round(t_score, 2),
                        "score_pct": pct,
                        "last_eval_at": row["last_eval_at"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                )
            return {
                "suites": suites,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + len(suites)) < total,
            }

    def get_suite(self, suite_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, project_id, env, slug, name, description,
                       config_json, rubric_md, excel_mapping_json,
                       source_xlsx_name, is_default, created_at, updated_at
                FROM eval_suites
                WHERE id = ?
                """,
                (suite_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Eval suite not found: {suite_id}")
            return {
                "id": row["id"],
                "project_id": row["project_id"],
                "env": row["env"],
                "slug": row["slug"],
                "name": row["name"],
                "description": row["description"],
                "config": self._safe_json_obj(row["config_json"]),
                "rubric_md": row["rubric_md"],
                "excel_mapping": self._safe_json_obj(row["excel_mapping_json"]),
                "source_xlsx_name": row["source_xlsx_name"],
                "is_default": bool(row["is_default"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def get_default_or_first_suite(self, project_id: str, env: EnvName) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM eval_suites
                WHERE project_id = ? AND env = ?
                ORDER BY is_default DESC, updated_at DESC, created_at ASC
                LIMIT 1
                """,
                (project_id, env),
            ).fetchone()
        if not row:
            return None
        return self.get_suite(row["id"])

    def upsert_suite(
        self,
        project_id: str,
        env: EnvName,
        name: str,
        *,
        suite_id: str | None = None,
        slug: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        rubric_md: str | None = None,
        excel_mapping: dict[str, Any] | None = None,
        source_xlsx_name: str | None = None,
        is_default: bool | None = None,
    ) -> dict[str, Any]:
        if env not in VALID_ENVS:
            raise ValueError(f"Invalid environment: {env}")
        now = time.time()
        with self._connect() as conn:
            existing_row = None
            if suite_id:
                existing_row = conn.execute(
                    "SELECT * FROM eval_suites WHERE id = ?", (suite_id,)
                ).fetchone()
            elif slug:
                existing_row = conn.execute(
                    "SELECT * FROM eval_suites WHERE project_id = ? AND env = ? AND slug = ?",
                    (project_id, env, slug),
                ).fetchone()

            if existing_row:
                target_id = existing_row["id"]
                next_name = name.strip() if name.strip() else existing_row["name"]
                next_desc = description if description is not None else existing_row["description"]
                next_cfg = (
                    json.dumps(config, ensure_ascii=False)
                    if config is not None
                    else existing_row["config_json"]
                )
                next_rubric = rubric_md if rubric_md is not None else existing_row["rubric_md"]
                next_map = (
                    json.dumps(excel_mapping, ensure_ascii=False)
                    if excel_mapping is not None
                    else existing_row["excel_mapping_json"]
                )
                next_xlsx = (
                    source_xlsx_name
                    if source_xlsx_name is not None
                    else existing_row["source_xlsx_name"]
                )
                next_default = (
                    1
                    if is_default is True
                    else (0 if is_default is False else int(existing_row["is_default"]))
                )
                if next_default == 1:
                    conn.execute(
                        "UPDATE eval_suites SET is_default = 0 WHERE project_id = ? AND env = ? AND id != ?",
                        (project_id, env, target_id),
                    )
                conn.execute(
                    """
                    UPDATE eval_suites
                    SET name = ?, description = ?, config_json = ?, rubric_md = ?,
                        excel_mapping_json = ?, source_xlsx_name = ?, is_default = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_name,
                        next_desc,
                        next_cfg,
                        next_rubric,
                        next_map,
                        next_xlsx,
                        next_default,
                        now,
                        target_id,
                    ),
                )
                return self.get_suite(target_id)

            base_slug = slugify_id(slug or name, fallback="suite")
            existing_slugs = {
                r["slug"]
                for r in conn.execute(
                    "SELECT slug FROM eval_suites WHERE project_id = ? AND env = ?",
                    (project_id, env),
                ).fetchall()
            }
            final_slug = base_slug
            cnt = 2
            while final_slug in existing_slugs:
                final_slug = f"{base_slug}-{cnt}"
                cnt += 1

            final_id = suite_id or self._suite_id_for(project_id, env, final_slug)
            while conn.execute("SELECT 1 FROM eval_suites WHERE id = ?", (final_id,)).fetchone():
                final_id = f"{final_id}-{cnt}"
                cnt += 1

            has_any = conn.execute(
                "SELECT 1 FROM eval_suites WHERE project_id = ? AND env = ? LIMIT 1",
                (project_id, env),
            ).fetchone()
            default_flag = 1 if (is_default is True or not has_any) else 0
            if default_flag == 1:
                conn.execute(
                    "UPDATE eval_suites SET is_default = 0 WHERE project_id = ? AND env = ?",
                    (project_id, env),
                )

            conn.execute(
                """
                INSERT INTO eval_suites(
                    id, project_id, env, slug, name, description,
                    config_json, rubric_md, excel_mapping_json, source_xlsx_name,
                    is_default, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    final_id,
                    project_id,
                    env,
                    final_slug,
                    name.strip() or final_slug,
                    description or "",
                    json.dumps(config or {}, ensure_ascii=False),
                    rubric_md or "",
                    json.dumps(excel_mapping or {}, ensure_ascii=False),
                    source_xlsx_name or "",
                    default_flag,
                    now,
                    now,
                ),
            )
        return self.get_suite(final_id)

    def delete_suite(self, suite_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM eval_suites WHERE id = ?", (suite_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Eval Cases
    # ------------------------------------------------------------------
    def upsert_cases(
        self,
        suite_id: str,
        cases: list[dict[str, Any]],
        *,
        replace_all: bool = False,
    ) -> int:
        now = time.time()
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM eval_suites WHERE id = ?", (suite_id,)).fetchone():
                raise KeyError(f"Eval suite not found: {suite_id}")
            if replace_all:
                conn.execute("DELETE FROM eval_cases WHERE suite_id = ?", (suite_id,))
                conn.execute("DELETE FROM eval_latest_results WHERE suite_id = ?", (suite_id,))
                next_order = 0
            else:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) AS mx FROM eval_cases WHERE suite_id = ?",
                    (suite_id,),
                ).fetchone()
                next_order = int(row["mx"]) + 1 if row else 0

            count = 0
            for idx, item in enumerate(cases):
                cid = str(item.get("id") or item.get("case_id") or "").strip()
                if not cid:
                    continue
                turns = normalize_turns(item)
                first_q = turns[0]["question"] if turns else ""
                tags = item.get("tags") if isinstance(item.get("tags"), list) else []
                sort_order = int(item["sort_order"]) if isinstance(item.get("sort_order"), int) else (next_order + idx)
                conn.execute(
                    """
                    INSERT INTO eval_cases(
                        suite_id, case_id, sort_order, first_question, turn_count, turns_json, tags_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(suite_id, case_id) DO UPDATE SET
                        sort_order = excluded.sort_order,
                        first_question = excluded.first_question,
                        turn_count = excluded.turn_count,
                        turns_json = excluded.turns_json,
                        tags_json = excluded.tags_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        suite_id,
                        cid,
                        sort_order,
                        first_q,
                        len(turns),
                        json.dumps(turns, ensure_ascii=False),
                        json.dumps(tags, ensure_ascii=False),
                        now,
                    ),
                )
                count += 1
            conn.execute("UPDATE eval_suites SET updated_at = ? WHERE id = ?", (now, suite_id))
            return count

    def delete_case(self, suite_id: str, case_id: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM eval_latest_results WHERE suite_id = ? AND case_id = ?",
                (suite_id, case_id),
            )
            cur = conn.execute(
                "DELETE FROM eval_cases WHERE suite_id = ? AND case_id = ?",
                (suite_id, case_id),
            )
            return cur.rowcount > 0

    def get_suite_summary(self, suite_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            agg = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_cases,
                    SUM(CASE WHEN COALESCE(r.status, '') IN ('PASS','PARTIAL','FAIL') THEN 1 ELSE 0 END) AS evaluated_cases,
                    SUM(CASE WHEN r.status = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                    SUM(CASE WHEN r.status = 'PARTIAL' THEN 1 ELSE 0 END) AS partial_count,
                    SUM(CASE WHEN r.status = 'FAIL' THEN 1 ELSE 0 END) AS fail_count,
                    COALESCE(SUM(CASE WHEN COALESCE(r.status, '') IN ('PASS','PARTIAL','FAIL') THEN r.score ELSE 0.0 END), 0.0) AS total_score,
                    MAX(r.updated_at) AS updated_at
                FROM eval_cases c
                LEFT JOIN eval_latest_results r
                    ON r.suite_id = c.suite_id AND r.case_id = c.case_id
                WHERE c.suite_id = ?
                """,
                (suite_id,),
            ).fetchone()
            fail_rows = conn.execute(
                """
                SELECT c.case_id
                FROM eval_cases c
                JOIN eval_latest_results r
                    ON r.suite_id = c.suite_id AND r.case_id = c.case_id
                WHERE c.suite_id = ? AND r.status IN ('FAIL', 'PARTIAL')
                ORDER BY c.sort_order ASC, c.case_id ASC
                """,
                (suite_id,),
            ).fetchall()

            total_cases = int(agg["total_cases"] or 0) if agg else 0
            evaluated = int(agg["evaluated_cases"] or 0) if agg else 0
            pass_cnt = int(agg["pass_count"] or 0) if agg else 0
            partial_cnt = int(agg["partial_count"] or 0) if agg else 0
            fail_cnt = int(agg["fail_count"] or 0) if agg else 0
            total_score = round(float(agg["total_score"] or 0.0), 2) if agg else 0.0
            score_pct = round((total_score / evaluated) * 100.0, 1) if evaluated else 0.0
            return {
                "total_cases": total_cases,
                "evaluated_cases": evaluated,
                "pass_count": pass_cnt,
                "partial_count": partial_cnt,
                "fail_count": fail_cnt,
                "total_score": total_score,
                "score_pct": score_pct,
                "failing_ids": [r["case_id"] for r in fail_rows],
                "updated_at": agg["updated_at"] if agg else None,
            }

    def query_cases(
        self,
        suite_id: str,
        *,
        status: str = "ALL",
        turn_filter: str = "ALL",
        search: str = "",
        sort_by: str = "ORDER",
        limit: int = 200,
        offset: int = 0,
        include_details: bool = False,
    ) -> dict[str, Any]:
        where_parts = ["c.suite_id = ?"]
        params: list[Any] = [suite_id]

        st_upper = (status or "ALL").upper()
        if st_upper in ("PASS", "PARTIAL", "FAIL"):
            where_parts.append("r.status = ?")
            params.append(st_upper)
        elif st_upper == "PENDING":
            where_parts.append("(r.status IS NULL OR r.status NOT IN ('PASS','PARTIAL','FAIL'))")

        tf_upper = (turn_filter or "ALL").upper()
        if tf_upper == "MULTI":
            where_parts.append("c.turn_count > 1")
        elif tf_upper == "SINGLE":
            where_parts.append("c.turn_count = 1")

        if search.strip():
            q = f"%{search.strip().lower()}%"
            where_parts.append(
                "(LOWER(c.case_id) LIKE ? OR LOWER(c.first_question) LIKE ? "
                "OR LOWER(COALESCE(r.comment, '')) LIKE ? OR LOWER(c.turns_json) LIKE ? "
                "OR LOWER(COALESCE(r.result_json, '')) LIKE ?)"
            )
            params.extend([q, q, q, q, q])

        where_sql = " AND ".join(where_parts)
        order_sql = "c.sort_order ASC, c.case_id ASC"
        if (sort_by or "").upper() == "STATUS":
            order_sql = (
                "CASE COALESCE(r.status, 'PENDING') "
                "WHEN 'FAIL' THEN 0 WHEN 'PARTIAL' THEN 1 WHEN 'PENDING' THEN 2 WHEN 'PASS' THEN 3 ELSE 4 END ASC, "
                "c.sort_order ASC, c.case_id ASC"
            )
        elif (sort_by or "").upper() == "ID":
            order_sql = "c.case_id ASC"

        with self._connect() as conn:
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM eval_cases c
                LEFT JOIN eval_latest_results r
                    ON r.suite_id = c.suite_id AND r.case_id = c.case_id
                WHERE {where_sql}
                """,
                tuple(params),
            ).fetchone()
            total = int(total_row["cnt"]) if total_row else 0

            select_cols = (
                "c.case_id, c.sort_order, c.first_question, c.turn_count, c.tags_json, "
                "c.turns_json, r.status, r.score, r.comment, r.updated_at, r.job_id"
            )
            if include_details:
                select_cols += ", r.result_json"

            rows = conn.execute(
                f"""
                SELECT {select_cols}
                FROM eval_cases c
                LEFT JOIN eval_latest_results r
                    ON r.suite_id = c.suite_id AND r.case_id = c.case_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                tuple([*params, max(1, min(limit, 1000)), max(0, offset)]),
            ).fetchall()

            items: list[dict[str, Any]] = []
            for row in rows:
                st = str(row["status"] or "PENDING").upper()
                if st not in ("PASS", "PARTIAL", "FAIL"):
                    st = "PENDING"
                entry: dict[str, Any] = {
                    "id": row["case_id"],
                    "sort_order": int(row["sort_order"]),
                    "first_question": row["first_question"],
                    "turn_count": int(row["turn_count"]),
                    "tags": self._safe_json_list(row["tags_json"]),
                    "status": st,
                    "score": float(row["score"]) if row["score"] is not None else None,
                    "comment": row["comment"] or "",
                    "updated_at": row["updated_at"],
                    "job_id": row["job_id"],
                }
                if include_details:
                    entry["turns"] = self._merge_case_and_result_turns(
                        self._safe_json_list(row["turns_json"]),
                        self._safe_json_obj(row["result_json"]) if row["result_json"] else None,
                    )
                items.append(entry)

            return {
                "cases": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + len(items)) < total,
            }

    def get_case_detail(self, suite_id: str, case_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT c.case_id, c.sort_order, c.first_question, c.turn_count,
                       c.turns_json, c.tags_json, c.updated_at AS case_updated_at,
                       r.job_id, r.status, r.score, r.comment, r.result_json, r.updated_at AS eval_updated_at
                FROM eval_cases c
                LEFT JOIN eval_latest_results r
                    ON r.suite_id = c.suite_id AND r.case_id = c.case_id
                WHERE c.suite_id = ? AND LOWER(c.case_id) = LOWER(?)
                """,
                (suite_id, case_id.strip()),
            ).fetchone()
            if not row:
                raise KeyError(f"Eval case '{case_id}' not found in suite '{suite_id}'.")

            case_turns = self._safe_json_list(row["turns_json"])
            res_obj = self._safe_json_obj(row["result_json"]) if row["result_json"] else None
            merged_turns = self._merge_case_and_result_turns(case_turns, res_obj)
            st = str(row["status"] or "PENDING").upper()
            if st not in ("PASS", "PARTIAL", "FAIL"):
                st = "PENDING"
            return {
                "id": row["case_id"],
                "suite_id": suite_id,
                "sort_order": int(row["sort_order"]),
                "turn_count": int(row["turn_count"]),
                "tags": self._safe_json_list(row["tags_json"]),
                "eval_review": {
                    "status": st,
                    "score": float(row["score"]) if row["score"] is not None else 0.0,
                    "comment": row["comment"] or "",
                },
                "turns": merged_turns,
                "job_id": row["job_id"],
                "updated_at": row["eval_updated_at"] or row["case_updated_at"],
            }

    def list_full_results_for_export(self, suite_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.case_id, c.turns_json, r.status, r.score, r.comment, r.result_json
                FROM eval_cases c
                LEFT JOIN eval_latest_results r
                    ON r.suite_id = c.suite_id AND r.case_id = c.case_id
                WHERE c.suite_id = ?
                ORDER BY c.sort_order ASC, c.case_id ASC
                """,
                (suite_id,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                case_turns = self._safe_json_list(row["turns_json"])
                res_obj = self._safe_json_obj(row["result_json"]) if row["result_json"] else None
                merged_turns = self._merge_case_and_result_turns(case_turns, res_obj)
                st = str(row["status"] or "PENDING").upper()
                out.append(
                    {
                        "id": row["case_id"],
                        "uat_review": {
                            "status": st,
                            "score": float(row["score"]) if row["score"] is not None else 0.0,
                            "comment": row["comment"] or "",
                        },
                        "turns": merged_turns,
                    }
                )
            return out

    # ------------------------------------------------------------------
    # Eval Runs, Results, and Logs
    # ------------------------------------------------------------------
    def create_run(
        self,
        *,
        job_id: str,
        project_id: str,
        env: EnvName,
        suite_id: str,
        endpoint: str = "",
        command: list[str] | None = None,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_runs(
                    job_id, project_id, env, suite_id, status, endpoint, command_json, summary_json, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, '{}', ?)
                """,
                (
                    job_id,
                    project_id,
                    env,
                    suite_id,
                    endpoint,
                    json.dumps(command or [], ensure_ascii=False),
                    now,
                ),
            )

    def append_run_log(self, job_id: str, seq: int, line: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO eval_run_logs(job_id, seq, line) VALUES (?, ?, ?)",
                (job_id, seq, line),
            )

    def get_run_logs(self, job_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT line FROM eval_run_logs WHERE job_id = ? ORDER BY seq ASC, id ASC",
                (job_id,),
            ).fetchall()
            return [r["line"] for r in rows]

    def finish_run(
        self,
        job_id: str,
        *,
        status: str,
        exit_code: int | None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT suite_id FROM eval_runs WHERE job_id = ?", (job_id,)
            ).fetchone()
            suite_id = row["suite_id"] if row else None
            sum_json = json.dumps(
                summary if summary is not None else (self.get_suite_summary(suite_id) if suite_id else {}),
                ensure_ascii=False,
            )
            conn.execute(
                """
                UPDATE eval_runs
                SET status = ?, exit_code = ?, summary_json = ?, finished_at = ?
                WHERE job_id = ?
                """,
                (status, exit_code, sum_json, now, job_id),
            )
            if suite_id:
                self._prune_old_runs_locked(conn, suite_id, keep=30)

    def record_case_result(
        self,
        *,
        suite_id: str,
        case_id: str,
        record: dict[str, Any],
        job_id: str | None = None,
    ) -> None:
        now = time.time()
        rev = record.get("uat_review") or record.get("eval_review") or {}
        status = str(rev.get("status") or "PENDING_REVIEW").upper()
        score = float(rev.get("score") or 0.0)
        comment = str(rev.get("comment") or "")
        res_json = json.dumps(record, ensure_ascii=False)

        with self._connect() as conn:
            if job_id:
                conn.execute(
                    """
                    INSERT INTO eval_run_results(job_id, suite_id, case_id, status, score, comment, result_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, case_id) DO UPDATE SET
                        status = excluded.status,
                        score = excluded.score,
                        comment = excluded.comment,
                        result_json = excluded.result_json,
                        updated_at = excluded.updated_at
                    """,
                    (job_id, suite_id, case_id, status, score, comment, res_json, now),
                )
            conn.execute(
                """
                INSERT INTO eval_latest_results(suite_id, case_id, job_id, status, score, comment, result_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(suite_id, case_id) DO UPDATE SET
                    job_id = COALESCE(excluded.job_id, eval_latest_results.job_id),
                    status = excluded.status,
                    score = excluded.score,
                    comment = excluded.comment,
                    result_json = excluded.result_json,
                    updated_at = excluded.updated_at
                """,
                (suite_id, case_id, job_id, status, score, comment, res_json, now),
            )

    def get_run(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM eval_runs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                raise KeyError(f"Eval run not found: {job_id}")
            return {
                "job_id": row["job_id"],
                "project_id": row["project_id"],
                "env": row["env"],
                "suite_id": row["suite_id"],
                "status": row["status"],
                "exit_code": row["exit_code"],
                "endpoint": row["endpoint"],
                "command": self._safe_json_list(row["command_json"]),
                "summary": self._safe_json_obj(row["summary_json"]),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }

    def list_runs(self, suite_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT job_id, project_id, env, suite_id, status, exit_code, endpoint, summary_json, started_at, finished_at
                FROM eval_runs
                WHERE suite_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (suite_id, max(1, min(limit, 100))),
            ).fetchall()
            return [
                {
                    "job_id": r["job_id"],
                    "project_id": r["project_id"],
                    "env": r["env"],
                    "suite_id": r["suite_id"],
                    "status": r["status"],
                    "exit_code": r["exit_code"],
                    "endpoint": r["endpoint"],
                    "summary": self._safe_json_obj(r["summary_json"]),
                    "started_at": r["started_at"],
                    "finished_at": r["finished_at"],
                }
                for r in rows
            ]

    def _prune_old_runs_locked(self, conn: sqlite3.Connection, suite_id: str, keep: int = 30) -> None:
        conn.execute(
            """
            DELETE FROM eval_runs
            WHERE suite_id = ? AND job_id NOT IN (
                SELECT job_id FROM eval_runs WHERE suite_id = ? ORDER BY started_at DESC LIMIT ?
            )
            """,
            (suite_id, suite_id, keep),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_json_obj(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _safe_json_list(raw: str | None) -> list[Any]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _merge_case_and_result_turns(
        case_turns: list[dict[str, Any]],
        res_obj: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        res_turns_by_num: dict[int, dict[str, Any]] = {}
        if res_obj and isinstance(res_obj.get("turns"), list):
            for idx, tr in enumerate(res_obj["turns"], 1):
                if isinstance(tr, dict):
                    tnum = int(tr.get("turn") or idx)
                    res_turns_by_num[tnum] = tr

        if not case_turns and res_turns_by_num:
            return [res_turns_by_num[k] for k in sorted(res_turns_by_num.keys())]

        merged: list[dict[str, Any]] = []
        for idx, ct in enumerate(case_turns, 1):
            rt = res_turns_by_num.get(idx) or {}
            rev = rt.get("uat_review") or rt.get("eval_review") or {"status": "PENDING"}
            merged.append(
                {
                    "turn": idx,
                    "question": ct.get("question") or rt.get("question") or "",
                    "expected_answer": ct.get("expected_answer") or rt.get("expected_answer") or "",
                    "expected_behavior": ct.get("expected_behavior") or rt.get("expected_behavior") or "",
                    "raw_response": rt.get("raw_response"),
                    "eval_review": rev,
                    "uat_review": rev,
                }
            )
        return merged
