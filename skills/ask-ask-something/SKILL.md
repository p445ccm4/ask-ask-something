---
name: ask-ask-something
description: Use when onboarding an AI agent or chatbot to Eval testing, importing Excel test sheets into the AskAsk* SQLite DB, running concurrent multi-turn LLM-as-a-Judge evaluations, debugging failing agent turns, or running post-change regression tests across sbx/dev/uat/prod environments
---

# AskAsk* — AI Agent Eval & Regression Toolkit

## Overview

End-to-end Eval toolkit for any HTTP/SSE AI agent (AskHR, AskLegal, AskIT, etc.) across environments (`sbx`, `dev`, `uat`, `prod`): import business Excel `.xlsx` sheets into the central SQLite DB (`ask_workbench.db`), run concurrent multi-turn evaluations with Gemini LLM-as-a-Judge (`PASS=1.0`, `PARTIAL=0.5`, `FAIL=0.0`), iterate on failing turns, enforce full regression suites after every change, and export results back into the original `.xlsx` format or CSV.

**When invoked as `/ask-ask-something` without a specific task**, present the 5 capabilities below and ask which step the user wants to start with:
1. **Import Excel Test Sheet** (`import_xlsx_suite` tool or `scripts/xlsx_to_uat.py inspect` → `import --db`)
2. **Onboard New Eval Suite** (configure endpoint + domain rubric via `create_or_update_eval_suite` in SQLite DB)
3. **Run Concurrent Eval Batch** (`run_eval_check` tool or `scripts/run_uat_batch.py --db ... --suite-id ...`)
4. **Debug Failing Cases & Run Regression** (targeted `--id`/`--turn` → `--runs 5` → full regression)
5. **Write Results Back to Excel / Export CSV** (`scripts/xlsx_to_uat.py update-xlsx --db ... --suite-id ...` or `export`)

## Single Source of Truth (SQLite DB — Never Pollute Target Repos)

All Eval Suites, Test Cases, Judge Rubrics, Endpoint Configs, Run Results, Logs, and `.xlsx` Templates live inside the **AskAsk* Workbench SQLite store**:

```text
app/agent-service/.data/
├── ask_workbench.db       # SQLite WAL SSOT (projects, environments, eval_suites, eval_cases, eval_runs, eval_latest_results, eval_run_logs)
├── templates/<suite>.xlsx # Stored original workbooks for format-preserving write-back
└── exports/               # Generated CSV / updated .xlsx exports
```

**CRITICAL RULE:** NEVER create, write, or commit `scripts/uat/*`, `.json`, `.csv`, or `.xlsx` eval files inside any target agent repository (`sbx`, `dev`, `uat`, or `prod`). Target repos should contain only service code!

## Onboarding & Excel Import

1. **Inspect Excel (if provided via CLI):** Run `python3 <skill-dir>/scripts/xlsx_to_uat.py inspect <file.xlsx>` to find the Q&A sheet, header row (may be Row 2 if Row 1 is a banner), and columns.
2. **Import into SQLite DB:**
   - **Inside AskAsk* Agent:** Call `import_xlsx_suite(xlsx_path=..., suite_name=..., env=...)` (or `create_or_update_eval_suite` + `upsert_eval_cases`).
   - **Via CLI:** Run `xlsx_to_uat.py import <file.xlsx> --db <ask_workbench.db> --project <project_id> --env dev --suite-name "My Suite"`.
   - Never transcribe 50+ Excel rows by hand.
3. **Configure endpoint & rubric:** Inspect the target agent's chat route and configure the Eval Suite's `config` (`endpoint`, `auth`, `request`, `response`, `judge`) and domain `rubric_md` in SQLite via `create_or_update_eval_suite`.
4. **Smoke-test:** Run `run_eval_check(limit=1)` (or `--limit 1` via CLI) before running the full suite.

## Mandatory Eval Debug & Regression Loop

1. **Baseline:** Call `get_eval_summary` / run `run_eval_check(case_ids="")` to establish a baseline score and list `FAIL`/`PARTIAL` case IDs.
2. **Diagnose:** Call `get_eval_case_detail(case_id=...)` to inspect `behavior_check`, `answer_check`, and `raw_response.sources` (RAG gap vs. prompt rule vs. multi-turn context vs. rubric ambiguity). Use `compare_envs(source_env=..., target_env=...)` when behavior differs across `sbx` / `dev` / `uat` / `prod`.
3. **Targeted Fix:** Edit code/prompt/retrieval in the target repo, then re-test **only** failing IDs (`run_eval_check(case_ids="Q1,E003")`; use `turn=N` to replay earlier turns from SQLite `eval_latest_results`).
4. **Stability Check:** Run `run_eval_check(case_ids="...", runs=5)` to confirm the fix holds under LLM/RAG non-determinism.
5. **REGRESSION GATE (Required After Every Change):** Prompt and retrieval tweaks frequently break unrelated questions. **Always run the full Eval Suite (`run_eval_check(case_ids="")`) after every change** and verify previously passing cases did not regress before handing off to the user to Deploy / Promote.
6. **Sign-off Export:** Use the UI **Export .xlsx** / **Export CSV** buttons, or run `xlsx_to_uat.py update-xlsx <template.xlsx> --db <ask_workbench.db> --suite-id <suite_id> -o <updated.xlsx>` (preserves all tabs, styles, borders, and merges).

## CLI Quick Reference (SQLite SSOT Mode)

Run `--help` on `scripts/run_uat_batch.py` or `scripts/xlsx_to_uat.py` for all flags.

| Task | Command |
| :--- | :--- |
| **Inspect Excel** | `python3 <skill>/scripts/xlsx_to_uat.py inspect <file.xlsx>` |
| **Import Excel → DB** | `python3 <skill>/scripts/xlsx_to_uat.py import <file.xlsx> --db <db> --project <id> --env dev --suite-name "<name>"` |
| **Full Eval / Regression** | `python3 <skill>/scripts/run_uat_batch.py --db <db> --suite-id <suite_id>` |
| **Debug specific turn** | `... --id T001 --turn 3` |
| **Variance check** | `... --id T001 --runs 5` |
| **Write back to Excel** | `python3 <skill>/scripts/xlsx_to_uat.py update-xlsx <orig.xlsx> --db <db> --suite-id <suite_id> -o <updated.xlsx>` |
| **Export CSV** | `python3 <skill>/scripts/xlsx_to_uat.py export --db <db> --suite-id <suite_id> -o <eval_results.csv>` |

## Common Mistakes

| Mistake | Fix |
| :--- | :--- |
| Writing `scripts/uat/*.json` or `.xlsx` into target repos | Store all suites, cases, configs, rubrics, and results in `ask_workbench.db` via host tools or `--db`. |
| Stopping after `--id` passes once | Run `runs=5` on fixed IDs, then run the **full regression suite**. |
| Hardcoding domain rules in `run_uat_batch.py` | Put domain rules in the Eval Suite's `rubric_md` and endpoint settings in `config_json`. |
| Hand-copying Excel rows | Use `import_xlsx_suite` or `xlsx_to_uat.py inspect` + `import --db`. |
