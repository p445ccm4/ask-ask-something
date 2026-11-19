---
name: ask-ask-something
description: Use when onboarding an AI agent or chatbot to UAT testing, importing Excel UAT test cases, running concurrent multi-turn LLM-as-a-Judge evaluations, debugging failing agent turns, or running post-change regression tests
---

# AskAsk* — AI Agent UAT & Regression Toolkit

## Overview

End-to-end UAT toolkit for any HTTP/SSE AI agent (AskHR, AskLegal, AskIT, etc.): import business Excel UAT sheets, run concurrent multi-turn evaluations with Gemini LLM-as-a-Judge (`PASS=1.0`, `PARTIAL=0.5`, `FAIL=0.0`), iterate on failing turns, enforce full regression tests after every change, and export results to CSV.

**When invoked as `/ask-ask-something` without a specific task**, present the 5 capabilities below and ask which step the user wants to start with:
1. **Import Excel UAT Log** (`scripts/xlsx_to_uat.py inspect` → `import`)
2. **Onboard New Agent** (create `scripts/uat/` config + domain rubric)
3. **Run Concurrent UAT Batch** (`scripts/run_uat_batch.py`)
4. **Debug Failing Cases & Run Regression** (targeted `--id`/`--turn` → `--runs 5` → full regression)
5. **Export Results to CSV** (`scripts/xlsx_to_uat.py export`)

## Where Project Files Live

Always store project-specific UAT files inside the **target agent's repo** (never inside this skill directory):

```text
<target-repo>/scripts/uat/
├── uat_config.json        # Committed (endpoint, auth mode, judge settings; no secrets)
├── judge_rubric.md        # Committed (domain rules, citation format, refusal phrasing)
├── excel_mapping.json     # Committed (reusable column mapping for Excel re-imports)
├── uat_questions.json     # Committed (canonical JSON generated from Excel)
└── results/               # Gitignored (uat_results.json, run1..N, exported CSVs)
```

## Onboarding & Excel Import

1. **Inspect Excel (if provided):** Run `python3 <skill-dir>/scripts/xlsx_to_uat.py inspect <file.xlsx>` to find the Q&A sheet, header row (may be Row 2 if Row 1 is a banner), and columns.
2. **Convert deterministically:** Save `scripts/uat/excel_mapping.json` (see `templates/excel_mapping.example.json`) and run `xlsx_to_uat.py import <file.xlsx> --mapping scripts/uat/excel_mapping.json -o scripts/uat/uat_questions.json`. Never transcribe 50+ Excel rows by hand.
3. **Configure endpoint & rubric:** Inspect the target agent's chat route and create `uat_config.json` + `judge_rubric.md` from `templates/`. For bespoke APIs, pass `--adapter my_adapter.py` (`build_request()` / `parse_response()`).
4. **Smoke-test:** Run with `--limit 1` before the full batch.

## Mandatory UAT Debug & Regression Loop

1. **Baseline:** Run the full suite to establish a baseline score and list `FAIL`/`PARTIAL` IDs.
2. **Diagnose:** Inspect `behavior_check`, `answer_check`, and `raw_response.sources` (RAG gap vs. prompt rule vs. multi-turn context vs. rubric ambiguity).
3. **Targeted Fix:** Edit code/prompt/retrieval, then re-test **only** failing IDs (`--id Q1,E003`; use `--turn N --from-results <prev.json>` to replay earlier turns).
4. **Stability Check:** Run `--id <fixed_IDs> --runs 5` to confirm the fix holds under LLM/RAG non-determinism.
5. **REGRESSION GATE (Required After Every Change):** Prompt and retrieval tweaks frequently break unrelated questions. **Always run the full `uat_questions.json` suite after every change** and verify previously-passing IDs did not regress before committing or deploying.
6. **Sign-off Export:** Run `xlsx_to_uat.py export <results.json> -o <out.csv>` (UTF-8-BOM CSV for Excel).

## Quick Reference

Run `--help` on `scripts/run_uat_batch.py` or `scripts/xlsx_to_uat.py` for all flags.

| Task | Command |
| :--- | :--- |
| **Inspect Excel** | `python3 <skill>/scripts/xlsx_to_uat.py inspect <file.xlsx>` |
| **Import Excel → JSON** | `python3 <skill>/scripts/xlsx_to_uat.py import <file.xlsx> --mapping scripts/uat/excel_mapping.json -o scripts/uat/uat_questions.json` |
| **Full UAT / Regression** | `python3 <skill>/scripts/run_uat_batch.py --config scripts/uat/uat_config.json -i scripts/uat/uat_questions.json -o scripts/uat/results/uat_results.json` |
| **Debug specific turn** | `... --id T001 --turn 3 --from-results scripts/uat/results/uat_results.json` |
| **Variance check** | `... --id T001 --runs 5` |
| **Export CSV** | `python3 <skill>/scripts/xlsx_to_uat.py export scripts/uat/results/uat_results.json -o scripts/uat/results/uat_results.csv` |

## Common Mistakes

| Mistake | Fix |
| :--- | :--- |
| Stopping after `--id` passes once | Run `--runs 5` on fixed IDs, then run the **full regression suite**. |
| Hardcoding domain rules or repo imports in `run_uat_batch.py` | Put domain rules in `judge_rubric.md` and endpoint settings in `uat_config.json`. |
| Storing `uat_questions.json` inside the skill folder | Keep all project UAT configs, questions, and results inside `<target-repo>/scripts/uat/`. |
| Hand-copying Excel rows into JSON | Use `xlsx_to_uat.py inspect` + `import` with `excel_mapping.json`. |
