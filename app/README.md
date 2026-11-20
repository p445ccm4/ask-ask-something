# AskAsk* Workbench (`app/`)

Web UI and Antigravity SDK backend living alongside the `ask-ask-something` plugin (`plugin.json` + `skills/`).

## Architecture

- **`app/agent-service/`** (FastAPI + `google-antigravity`, port `8000`):
  - Runs the Antigravity Python SDK directly with `skills_paths` pointing to `skills/` and `SessionContinuationMode.CREATE_OR_RESUME`.
  - Exposes custom host tools (`get_uat_summary`, `get_uat_case_detail`, `run_uat_check`, `get_git_diff`) that reuse `skills/ask-ask-something/scripts/run_uat_batch.py` and `xlsx_to_uat.py`.
  - Enforces 3 execution modes (`read_only`, `ask_before_fix` via `ApprovalBroker`, `sandboxed_auto` via `RunCommandConfig(enable_sandbox=True)`) while always blocking `git push` and destructive commands for the AI agent.
  - Provides a **human-only** `deploy_service` triggered strictly from the UI's **Deploy to DEV** and **Deploy to UAT** buttons (`git push origin main` scoped to the active service directory, preserving UAT's `src/config.py` during DEV → UAT promotion).
- **`app/web/`** (Next.js App Router + BFF, port `3000`):
  - Proxies all JSON and SSE requests through `/api/*` route handlers so a single port (`3000`) serves the entire app in Cloud Shell Web Preview and provides a clean BFF seam for future auth or database persistence.

## Quick Start (Local / Cloud Shell)

From the repository root:

```bash
./app/dev.sh
```

`dev.sh` automatically runs `setup_mounts.sh` to bind-mount `.venv`, `node_modules`, `.next`, and caches onto `/tmp` (preserving `/home` disk quota), starts FastAPI on `:8000`, and starts Next.js on `:3000`.

### Environment Configuration

Copy `app/agent-service/.env.example` to `app/agent-service/.env` to set your Vertex AI project/location, model override, and optional default repositories:

```env
VERTEX_PROJECT_ID=your-gcp-project-id
VERTEX_LOCATION=global
AGENT_MODEL=
DEFAULT_WORKSPACES_JSON='[{"id":"sample-dev","name":"Sample Agent (DEV)","path":"/path/to/dev-repo/sample-agent-service","uat_path":"/path/to/uat-repo/sample-agent-service","env":"dev"}]'
```

## Running Tests

```bash
# Python backend tests
cd app/agent-service && UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -v

# Next.js lint & production build
cd app/web && npm run lint && npm run build
```
