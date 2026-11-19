# AskAsk* (`ask-ask-something`)

[繁體中文](#繁體中文) | [English](#english)

---

## 繁體中文

做 AI Agent（AskHR、AskLegal、AskIT……乜都 Ask 一餐）最煩係咩？次次改完 prompt 或者 RAG，又要人手逐條 UAT 問題 copy & paste 試過晒，仲要驚改好 A 題但整死 B 題！

**AskAsk\*** 幫你將成套 UAT 測試、自動批改、除錯同 Regression Test 變成一句指令搞掂。

### 先睇效果：實際用起上嚟係點？

**1. 喺對話直接打 `/ask-ask-something`，掉個 User 畀嘅 Excel 落去：**
> `/ask-ask-something 幫我 import AskLegal_UAT.xlsx，set 好 config 同 rubric，然後並發跑一次 UAT baseline！`

**2. 幾十秒就自動並發跑晒多輪對話 + Gemini LLM-as-a-Judge 逐條批改：**
```text
================================================================================
AskLegal Agent - Concurrent UAT Batch Runner
Endpoint URL: https://ask-legal-service-dev.example.run.app/chat
Input File  : scripts/uat/uat_questions.json (11 conversations)
Concurrency : 5 parallel worker(s)
LLM Eval    : ENABLED (judge=gemini-4-argon)
================================================================================

[1/11] Finished T001 (3 turn(s)) in 57.9s | Eval: PASS (score=1.0)
  -> [T001 T1] (PASS) Q: What is the standard NDA retention period? | A: According to the Legal Document Retention Policy...
     Review: Accurately stated the retention rule with exact section citation and no page numbers.
  -> [T001 T2] (PASS) Q: Who approves exceptions to this period? | A: Exceptions require written approval from Legal Counsel...
     Review: Retained Turn 1 context accurately without confusing unrelated approval matrices.
[11/11] Finished T011 (1 turn(s)) in 14.6s | Eval: PARTIAL (score=0.5)
  -> [T011 T1] (PARTIAL) Q: Bilingual policy question... | A: ...
     Review: Followed formatting and citation rules, but missed a supplementary notice period item because that source was not retrieved.

================================================================================
Completed 11/11 questions in 66.8s (concurrency=5). Saved to: scripts/uat/results/uat_results.json
Evaluation Summary: PASS=10, PARTIAL=1, FAIL=0 | Total Score: 10.5/11 (95.5%)
================================================================================
```

**3. 發現邊條 Fail？秒速重播嗰個 Turn 嚟 debug，改完再跑 5 次抽查 + 全套 Regression，最後原汁原味寫返入原版 Excel 直接覆蓋交數：**
- 淨係重跑第 3 個 Turn（自動重播 Turn 1–2，唔使由頭等）：`--id T001 --turn 3 --from-results uat_results.json`
- 抽查有冇時得時唔得（LLM 隨機性）：`--id T011 --runs 5`
- 改完嘢必跑全套 Regression，確保冇整死其他題目
- **原格式寫返落 Excel（`update-xlsx`）**：保留晒原本所有分頁、字體、框線、合併儲存格同公式，直接填返 `Actual Answers` / `Actual Source` / `Remarks`，覆蓋原檔就交得功課！（亦支援匯出 UTF-8-BOM CSV）

---

### 佢幫到你啲咩？

- **Excel 原格式雙向讀寫（零額外套件）**：純 Python 內置 library 讀取 Business User 嘅 `.xlsx`（無論 Header 喺第 1 行定第 2 行、夾雜 UI 測試行定多輪對話都識自動過濾同整合），跑完仲可以**原格式寫返入原本份 `.xlsx`**，唔使手動 copy & paste！
- **多線程並發跑多輪對話**：開 5–10 個 worker 同時跑，幾十條 UAT 一分鐘內收工，內置 429/5xx 自動重試。
- **Gemini LLM-as-a-Judge 自動批改**：對比 `expected_answer`、`expected_behavior` 同 retrieved sources，自動分 `PASS (1.0)` / `PARTIAL (0.5)` / `FAIL (0.0)` 並寫明原因。
- **通用任何 Agent 專案**：完全唔使改你原本嘅 repo code；Endpoint、驗證方式（Cloud Run `gcloud` token / Bearer / API Key / 本地免驗證）、Request/Response 格式寫落 `uat_config.json`，專案專屬規矩寫落 `judge_rubric.md` 就用得（奇形怪狀嘅 API 仲可以加 `--adapter` 自訂）。
- **內置 UAT Debug & Regression 流程**：提醒 Coding Agent 每次改完 prompt/RAG 都要跑完整 Regression，唔好中伏。

---

### 點樣裝同開始用？

#### 方式一：用 `npx skills` 一行搞掂（最爽）
支援 Antigravity、Gemini CLI、Claude Code、Cursor 同 Codex：
```bash
npx skills add git@github.com:p445ccm4/ask-ask-something.git
```

#### 方式二：直接 `git clone` 當 Antigravity Plugin 用
全機通用（所有 Project 都用得）：
```bash
git clone git@github.com:p445ccm4/ask-ask-something.git ~/.gemini/config/plugins/ask-ask-something
```
或者淨係放喺單一 Project 入面：
```bash
git clone git@github.com:p445ccm4/ask-ask-something.git .agents/plugins/ask-ask-something
```

#### 方式三：公司機上唔到 GitHub？離線 ZIP 手動裝都得！
如果 Terminal 俾 Firewall 擋住連唔到 `github.com`，唔使慌：
1. 喺瀏覽器開 GitHub，撳 **Code → Download ZIP**（會 download `ask-ask-something-main.zip`），傳送去開發機或者 Cloud Shell。
2. 解壓落 Antigravity 嘅 plugins 資料夾就掂：
   ```bash
   mkdir -p ~/.gemini/config/plugins
   unzip ask-ask-something-main.zip -d ~/.gemini/config/plugins/
   rm -rf ~/.gemini/config/plugins/ask-ask-something
   mv ~/.gemini/config/plugins/ask-ask-something-main ~/.gemini/config/plugins/ask-ask-something
   ```
   *（用 Claude Code / Gemini CLI / Codex / Cursor 嘅話，將解壓出嚟嘅 `skills/ask-ask-something/` 成個抄去 `~/.agents/skills/ask-ask-something/` 就得。）*

#### 裝好之後點用？
打開你嘅 AI Agent Project，喺對話輸入 **`/ask-ask-something`** 就會見到 5 大功能選單，跟住指示做就得！所有專案專屬嘅 `uat_config.json`、`judge_rubric.md`、`uat_questions.json` 會安全放喺你個專案嘅 `scripts/uat/` 入面，唔會撈亂其他專案。

#### 事前準備
- Python 3.10+
- `xlsx_to_uat.py`：純 Python 標準庫，乜都唔使額外裝
- `run_uat_batch.py`：需要 `httpx` 同 `google-genai`（`pip install httpx google-genai`），加埋 Vertex AI ADC（`gcloud auth application-default login`）或者 `GEMINI_API_KEY` 畀 Judge 評分用

---

## English

Tired of manually copy-pasting dozens of UAT questions after every prompt or RAG tweak — and worrying that fixing one question silently broke another?

**AskAsk\*** is a reusable Agent Skill & Antigravity Plugin that turns Excel UAT sheets, concurrent multi-turn testing, Gemini LLM-as-a-Judge grading, turn-level debugging, and full regression testing into one command: **`/ask-ask-something`**.

### Example Usage & Outcome

**1. Invoke `/ask-ask-something` in chat with your business UAT Excel file:**
> `/ask-ask-something Import AskLegal_UAT.xlsx, set up config & rubric for this repo, and run a concurrent UAT baseline.`

**2. Runs multi-turn conversations concurrently and grades every turn with Gemini LLM-as-a-Judge:**
```text
================================================================================
AskLegal Agent - Concurrent UAT Batch Runner
Endpoint URL: https://ask-legal-service-dev.example.run.app/chat
Input File  : scripts/uat/uat_questions.json (11 conversations)
Concurrency : 5 parallel worker(s)
LLM Eval    : ENABLED (judge=gemini-4-argon)
================================================================================

[1/11] Finished T001 (3 turn(s)) in 57.9s | Eval: PASS (score=1.0)
  -> [T001 T1] (PASS) Q: What is the standard NDA retention period? | A: According to the Legal Document Retention Policy...
     Review: Accurately stated the retention rule with exact section citation and no page numbers.
  -> [T001 T2] (PASS) Q: Who approves exceptions to this period? | A: Exceptions require written approval from Legal Counsel...
     Review: Retained Turn 1 context accurately without confusing unrelated approval matrices.
[11/11] Finished T011 (1 turn(s)) in 14.6s | Eval: PARTIAL (score=0.5)
  -> [T011 T1] (PARTIAL) Q: Bilingual policy question... | A: ...
     Review: Followed formatting and citation rules, but missed a supplementary notice period item because that source was not retrieved.

================================================================================
Completed 11/11 questions in 66.8s (concurrency=5). Saved to: scripts/uat/results/uat_results.json
Evaluation Summary: PASS=10, PARTIAL=1, FAIL=0 | Total Score: 10.5/11 (95.5%)
================================================================================
```

**3. Debug fast, check stability, run full regression, and write results straight back into the original Excel file:**
- Replay earlier turns when debugging Turn 3: `--id T001 --turn 3 --from-results uat_results.json`
- Check LLM/RAG consistency across runs: `--id T011 --runs 5`
- Run the full regression suite after every change to catch unintended regressions
- **Format-preserving Excel write-back (`update-xlsx`)**: fills `Actual Answers`, `Actual Source`, and `Remarks` straight back into a copy of the original `.xlsx` (preserving all sheets, fonts, borders, merges, and formulas) so users can simply overwrite their document (CSV export also supported).

---

### What It Can Do

- **Zero-Dependency Excel Round-Trip (`scripts/xlsx_to_uat.py`):** Pure Python stdlib (no `openpyxl` needed) — inspects arbitrary business `.xlsx` layouts (including multi-row headers and blank UI rows), converts them into `uat_questions.json`, and writes results **straight back into the original `.xlsx` format** (or UTF-8-BOM CSV).
- **Concurrent Multi-Turn Runner (`scripts/run_uat_batch.py`):** Runs conversations in parallel with full turn history and automatic 429/5xx backoff retries.
- **Automated Gemini LLM-as-a-Judge:** Evaluates `behavior_check` and `answer_check` against `expected_answer`, `expected_behavior`, and retrieved sources (`PASS=1.0`, `PARTIAL=0.5`, `FAIL=0.0`).
- **Repo-Agnostic & Pluggable:** Zero imports from your app codebase. Configure endpoint, auth (`gcloud-id-token`, `bearer-env`, `header-env`, `none`), request/response formats (`gemini-contents`, `openai-messages`, `simple-chat`, `sse`/`json`, or custom `--adapter`), and domain rules (`judge_rubric.md`) inside `<target-repo>/scripts/uat/`.
- **Built-in Debug & Regression Discipline:** Guides coding agents through Baseline → Diagnose → Targeted `--id`/`--turn` fix → `--runs 5` stability check → **Mandatory Full Regression Gate** → CSV Export.

---

### How to Install & Use

#### Option 1: Install as a Skill (`npx skills`)
Works with Antigravity, Gemini CLI, Claude Code, Cursor, and Codex:
```bash
npx skills add git@github.com:p445ccm4/ask-ask-something.git
```

#### Option 2: Install as an Antigravity Plugin (`git clone`)
Global (all projects):
```bash
git clone git@github.com:p445ccm4/ask-ask-something.git ~/.gemini/config/plugins/ask-ask-something
```
Workspace-scoped (inside a project repo):
```bash
git clone git@github.com:p445ccm4/ask-ask-something.git .agents/plugins/ask-ask-something
```

#### Option 3: Offline / Manual ZIP Install (No Terminal GitHub Access)
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

#### Getting Started
Open your AI agent repo and type **`/ask-ask-something`** in chat to see all 5 capabilities and kick off onboarding, Excel import, UAT runs, or debugging.

#### Prerequisites
- Python 3.10+
- `xlsx_to_uat.py`: Python standard library only (zero third-party dependencies)
- `run_uat_batch.py`: `httpx` and `google-genai` (`pip install httpx google-genai`), plus Vertex AI ADC (`gcloud auth application-default login`) or `GEMINI_API_KEY` for LLM-as-a-Judge
