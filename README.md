# AskAsk* (`ask-ask-something`)

A reusable Agent Skill and Antigravity Plugin for running **concurrent, multi-turn UAT batch evaluations** against any HTTP/SSE AI agent endpoint (AskHR, AskLegal, AskIT, etc.) with **Gemini LLM-as-a-Judge** grading.

## Install

### Option 1: Install as a Skill (`npx skills`)
Works with Antigravity, Gemini CLI, Claude Code, Cursor, and Codex:

```bash
npx skills add git@github.com:p445ccm4/ask-ask-something.git
```

### Option 2: Install as an Antigravity Plugin
Clone into your global Antigravity plugins directory:

```bash
git clone git@github.com:p445ccm4/ask-ask-something.git ~/.gemini/config/plugins/ask-ask-something
```

Or workspace-scoped inside a project repo:

```bash
git clone git@github.com:p445ccm4/ask-ask-something.git .agents/plugins/ask-ask-something
```

## What's Included

- `skills/running-agent-uat-eval/SKILL.md` — Onboarding workflow, debugging loop (`--id`, `--turn` replay, `--runs` variance checks), and custom adapter hook guidance.
- `skills/running-agent-uat-eval/scripts/run_uat_batch.py` — Standalone, zero-repo-import concurrent UAT runner supporting:
  - Auth modes: `gcloud-id-token` (Cloud Run), `bearer-env`, `header-env`, `none`
  - Request presets: `gemini-contents`, `openai-messages`, `simple-chat` (or `--adapter <file.py>`)
  - Response modes: `sse` or `json` with dot-path field extraction
  - Domain-specific judge rules via `--rubric <file.md>`
- `skills/running-agent-uat-eval/templates/` — Starter `uat_config.example.json`, `judge_rubric.example.md`, and `uat_questions.example.json`.

## Prerequisites

- Python 3.10+
- `httpx` and `google-genai` (`pip install httpx google-genai`)
- Vertex AI ADC (`gcloud auth application-default login`) or `GEMINI_API_KEY` for LLM-as-a-Judge evaluation
