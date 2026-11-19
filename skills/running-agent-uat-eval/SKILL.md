---
name: running-agent-uat-eval
description: Use when testing, debugging, or regression-checking an AI agent or chatbot with multi-turn UAT cases, setting up LLM-as-a-Judge batch evaluation, or measuring non-deterministic response consistency across runs
---

# Running Agent UAT Evaluations

## Overview

Run concurrent, multi-turn UAT suites against any HTTP/SSE AI agent endpoint and grade each turn with Gemini LLM-as-a-Judge (`PASS=1.0`, `PARTIAL=0.5`, `FAIL=0.0`). Keep the runner repo-agnostic: put project-specific endpoint details in `uat_config.json` and domain rules in `judge_rubric.md`.

## When to Use

- Onboarding a new AI agent project (e.g., AskLegal, AskIT, AskHR) to automated multi-turn UAT testing
- Iterating on a failing prompt, RAG retrieval rule, or multi-turn context bug
- Checking for non-deterministic regressions before merging or deploying (`--runs N`)

**When NOT to use:** Pure unit tests of Python helper functions that do not call an agent endpoint.

## Onboarding a New Agent Project

1. **Inspect the target agent's chat route** to determine URL, auth mechanism (`gcloud-id-token`, `bearer-env`, `header-env`, or `none`), request schema (`gemini-contents`, `openai-messages`, `simple-chat`), and response format (`sse` or `json` plus JSON field paths).
2. **Copy templates** from `templates/` into the target project (e.g., `scripts/uat/`):
   - `templates/uat_config.example.json` → `uat_config.json`
   - `templates/judge_rubric.example.md` → `judge_rubric.md` (encode citation rules, refusal phrasing, and domain negative constraints here — never hardcode them in the runner)
   - `templates/uat_questions.example.json` → `uat_questions.json`
3. **Smoke-test one case** before running the full suite:
   ```bash
   python3 <skill-dir>/scripts/run_uat_batch.py --config uat_config.json -i uat_questions.json -o uat_results.json --limit 1
   ```

## Quick Reference

Run `python3 <skill-dir>/scripts/run_uat_batch.py --help` for all flags.

| Workflow | Command |
| :--- | :--- |
| **Full concurrent batch** | `python3 <skill-dir>/scripts/run_uat_batch.py --config uat_config.json -i uat_questions.json -o uat_results.json` |
| **Debug specific test ID(s)** | `... --id T001,T002` |
| **Replay up to Turn N** (reuses earlier turns from cache) | `... --id T001 --turn 3 --from-results uat_results.json` |
| **Stability / variance check** | `... --runs 5` |
| **Capture outputs without judge** | `... --no-eval` |

## Custom Adapter Hook

If an agent uses a bespoke request/response contract (e.g., stateful session IDs or ADK `/run_sse`), pass `--adapter my_adapter.py` implementing one or both functions:
- `build_request(history_turns, question, req_cfg) -> dict`
- `parse_response(raw_json_or_sse_lines) -> {"text": str, "sources": list, "error": str | None}`

## Common Mistakes

| Mistake | Fix |
| :--- | :--- |
| Hardcoding domain rules or repo imports into `run_uat_batch.py` | Keep domain constraints in `judge_rubric.md` and endpoint settings in `uat_config.json`. |
| Claiming a fix works after 1 passing run | Run `--runs 5` on affected IDs to verify non-deterministic LLM/RAG stability. |
| Re-running Turn 1–2 manually when debugging Turn 3 | Use `--id <ID> --turn 3 --from-results <prev.json>` to replay prior turns deterministically. |
| Writing results over the input questions file | Keep `-i uat_questions.json` and `-o uat_results.json` separate. |
| Omitting negative constraints in `expected_behavior` | Explicitly state what the agent must NOT do (e.g., no page numbers, no fabricated links) so the judge enforces it. |
