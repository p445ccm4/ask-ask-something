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

## First-Time Setup on Cloud Shell

If you just cloned this repository, complete these one-time steps before running UAT or using the Maintainer Agent:

1. **Verify prerequisites** (`uv`, Node.js/`npm`, and `gcloud` CLI):
   ```bash
   command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
   node -v && npm -v && gcloud --version
   ```
   *(Cloud Shell includes `node`, `npm`, `gcloud`, and `sudo` for the `/tmp` bind mounts in `setup_mounts.sh`.)*

2. **Authenticate `gcloud` and Vertex AI ADC** (used by `google-antigravity`, the Vertex AI LLM-as-a-Judge, and `gcloud-id-token` UAT targets):
   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project your-gcp-project-id
   ```

3. **Create `app/agent-service/.env`** (this file is gitignored):
   ```bash
   cp app/agent-service/.env.example app/agent-service/.env
   ```
   Edit `app/agent-service/.env` and set `VERTEX_PROJECT_ID=your-gcp-project-id` (and optionally `DEFAULT_WORKSPACES_JSON`):
   ```env
   VERTEX_PROJECT_ID=your-gcp-project-id
   VERTEX_LOCATION=global
   AGENT_MODEL=
   DEFAULT_WORKSPACES_JSON='[{"id":"sample-dev","name":"Sample Agent (DEV)","path":"/path/to/dev-repo/sample-agent-service","uat_path":"/path/to/uat-repo/sample-agent-service","env":"dev"}]'
   ```

4. **Start the Workbench:**
   From the repository root:
   ```bash
   ./app/dev.sh
   ```
   `dev.sh` automatically runs `setup_mounts.sh` to bind-mount `.venv`, `node_modules`, `.next`, and caches onto `/tmp` (preserving `/home` disk quota), installs dependencies on first run, starts FastAPI on `127.0.0.1:8000`, and starts Next.js on `0.0.0.0:3000`. In Cloud Shell, open **Web Preview → Preview on port 3000**.

5. **Add a target agent repo and run UAT:**
   - If you left `DEFAULT_WORKSPACES_JSON` empty, click the **`+`** button next to the workspace selector in the UI header to register your local agent repository path.
   - Your target repository must contain `scripts/uat/uat_config.json` and `scripts/uat/uat_questions.json` (or legacy `scripts/dev/` files). If not yet initialized, import an Excel UAT sheet first with `skills/ask-ask-something/scripts/xlsx_to_uat.py` or `/ask-ask-something`.
   - **Target endpoint access:**
     - **Cloud Run (`gcloud-id-token`):** Your `gcloud` user must have `roles/run.invoker` on the target Cloud Run service.
     - **Bearer / Header auth (`bearer-env` / `header-env`):** Export the required token env var (e.g. `export BEARER_TOKEN=...`) in the shell before launching `./app/dev.sh`.
     - **Private / intranet URLs:** Public Cloud Shell cannot reach private `10.x.x.x` intranet endpoints; run from a host with network access or point `uat_config.json` at a reachable Cloud Run endpoint.

## Running Tests

```bash
# Python backend tests
cd app/agent-service && UV_PYTHON_INSTALL_DIR=/tmp/uv-python uv run pytest -v

# Next.js lint & production build
cd app/web && npm run lint && npm run build
```
