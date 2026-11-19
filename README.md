# AskAsk* (`ask-ask-something`)

A reusable Agent Skill and Antigravity Plugin for **end-to-end AI agent UAT testing, debugging, and regression checking** (AskHR, AskLegal, AskIT, etc.) with concurrent multi-turn execution, Gemini LLM-as-a-Judge grading, and zero-dependency Excel import/export.

Once installed, type **`/ask-ask-something`** in chat to see all capabilities and start a workflow.

## Install

### Option 1: Install as a Skill (`npx skills`)
Works with Antigravity, Gemini CLI, Claude Code, Cursor, and Codex:

```bash
npx skills add git@github.com:p445ccm4/ask-ask-something.git
```

### Option 2: Install as an Antigravity Plugin (`git clone`)
Global (all projects):
```bash
git clone git@github.com:p445ccm4/ask-ask-something.git ~/.gemini/config/plugins/ask-ask-something
```

Workspace-scoped (inside a project repo):
```bash
git clone git@github.com:p445ccm4/ask-ask-something.git .agents/plugins/ask-ask-something
```

### Option 3: Offline / Manual ZIP Install (No Terminal GitHub Access)
If your terminal cannot reach `github.com`:
1. Click **Code → Download ZIP** on GitHub (`ask-ask-something-main.zip`) and transfer it to your dev machine / Cloud Shell.
2. Unzip it directly into Antigravity's plugins folder:
   ```bash
   mkdir -p ~/.gemini/config/plugins
   unzip ask-ask-something-main.zip -d ~/.gemini/config/plugins/
   rm -rf ~/.gemini/config/plugins/ask-ask-something
   mv ~/.gemini/config/plugins/ask-ask-something-main ~/.gemini/config/plugins/ask-ask-something
   ```
   *(Or for Claude Code / Gemini CLI / Codex / Cursor, copy `skills/ask-ask-something/` into `~/.agents/skills/ask-ask-something/`.)*

## What's Included

- `skills/ask-ask-something/SKILL.md` — Unified `/ask-ask-something` workflow: Excel import, agent onboarding, concurrent UAT execution, targeted debugging (`--id`, `--turn` replay, `--runs` variance), mandatory full regression gate, and CSV export.
- `skills/ask-ask-something/scripts/run_uat_batch.py` — Standalone, zero-repo-import concurrent UAT runner supporting:
  - Auth modes: `gcloud-id-token` (Cloud Run), `bearer-env`, `header-env`, `none`
  - Request presets: `gemini-contents`, `openai-messages`, `simple-chat` (or `--adapter <file.py>`)
  - Response modes: `sse` or `json` with dot-path field extraction
  - Domain-specific judge rules via `--rubric <file.md>`
- `skills/ask-ask-something/scripts/xlsx_to_uat.py` — Zero-dependency (Python stdlib only) `.xlsx` inspector, Excel → `uat_questions.json` importer, and `uat_results.json` → UTF-8-BOM CSV exporter.
- `skills/ask-ask-something/templates/` — Starter `uat_config.example.json`, `judge_rubric.example.md`, `excel_mapping.example.json`, and `uat_questions.example.json`.

## Prerequisites

- Python 3.10+
- `xlsx_to_uat.py`: Python standard library only (zero third-party dependencies)
- `run_uat_batch.py`: `httpx` and `google-genai` (`pip install httpx google-genai`), plus Vertex AI ADC (`gcloud auth application-default login`) or `GEMINI_API_KEY` for LLM-as-a-Judge
