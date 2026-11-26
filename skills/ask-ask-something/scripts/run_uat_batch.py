#!/usr/bin/env python3
"""
run_uat_batch.py - Generic multi-turn concurrent UAT batch runner with LLM-as-a-Judge.

Executes single-turn or multi-turn test cases against any HTTP/SSE AI agent endpoint
concurrently across conversations, evaluates each turn with Gemini LLM-as-a-Judge
(using a generic core rubric plus an optional domain rubric file), and writes
structured JSON results.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import random
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

_orig_getaddrinfo = socket.getaddrinfo
_dns_cache: dict[tuple[Any, ...], Any] = {}


def _cached_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
    """Cache DNS resolutions with brief retry to avoid transient lookup failures under concurrency."""
    key = (args, tuple(sorted(kwargs.items())))
    if key in _dns_cache:
        return _dns_cache[key]
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            res = _orig_getaddrinfo(*args, **kwargs)
            if res:
                _dns_cache[key] = res
            return res
        except socket.gaierror as exc:
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    return _orig_getaddrinfo(*args, **kwargs)


socket.getaddrinfo = _cached_getaddrinfo  # type: ignore[assignment]

DEFAULT_CONCURRENCY = 5
DEFAULT_JUDGE_MODEL = "gemini-4-argon"
DEFAULT_JUDGE_LOCATION = "global"
DEFAULT_TIMEOUT_SECONDS = 180.0

RETRYABLE_ERROR_MARKERS = (
    "401",
    "429",
    "RESOURCE_EXHAUSTED",
    "500",
    "502",
    "503",
    "504",
    "Temporary failure in name resolution",
    "Errno -3",
    "Name or service not known",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "RemoteProtocolError",
    "Server disconnected",
)

_cached_token: str | None = None
_token_timestamp: float = 0.0
_TOKEN_TTL_SECONDS = 2700.0
_auth_env_synced: bool = False
_judge_client: Any = None
_judge_client_created_at: float = 0.0
_JUDGE_CLIENT_TTL_SECONDS = 600.0


def _extract_path(obj: Any, path: str | None) -> Any:
    """Resolve a dot-separated field path (supporting list indices) from a nested dict/list."""
    if not path or obj is None:
        return None
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            return None
    return cur


def _sync_cloudshell_auth_env(force: bool = False) -> None:
    """Discover active Cloud Shell CLOUDSDK_CONFIG / ADC from user terminal processes or /tmp."""
    global _auth_env_synced
    if _auth_env_synced and not force:
        return
    _auth_env_synced = True

    if not Path("/proc").is_dir():
        return

    uid = os.getuid()
    candidate_configs: list[str] = []
    candidate_ports: list[str] = []
    candidate_adcs: list[str] = []

    proc_dirs: list[tuple[float, Path]] = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                st = p.stat()
                if st.st_uid == uid:
                    proc_dirs.append((st.st_mtime, p))
            except Exception:
                pass
    proc_dirs.sort(key=lambda x: x[0], reverse=True)

    for _, p in proc_dirs:
        try:
            raw_env = (p / "environ").read_bytes().split(b"\x00")
            env_map: dict[str, str] = {}
            for entry in raw_env:
                if b"=" in entry:
                    k, v = entry.split(b"=", 1)
                    env_map[k.decode("utf-8", errors="ignore")] = v.decode(
                        "utf-8", errors="ignore"
                    )
            cfg = env_map.get("CLOUDSDK_CONFIG")
            if cfg and Path(cfg).is_dir() and cfg not in candidate_configs:
                candidate_configs.append(cfg)
            port = env_map.get("DEVSHELL_CLIENT_PORT")
            if port and port not in candidate_ports:
                candidate_ports.append(port)
            adc = env_map.get("GOOGLE_APPLICATION_CREDENTIALS")
            if adc and Path(adc).is_file() and adc not in candidate_adcs:
                candidate_adcs.append(adc)
        except Exception:
            continue

    tmp_dirs: list[tuple[float, Path]] = []
    tmp_root = Path("/tmp")
    if tmp_root.is_dir():
        for td in tmp_root.glob("tmp.*"):
            try:
                st = td.stat()
                if td.is_dir() and st.st_uid == uid and (td / "credentials.db").is_file():
                    tmp_dirs.append((st.st_mtime, td))
            except Exception:
                pass
    tmp_dirs.sort(key=lambda x: x[0], reverse=True)
    for _, td in tmp_dirs:
        s = str(td)
        if s not in candidate_configs:
            candidate_configs.append(s)

    if candidate_ports and not os.environ.get("DEVSHELL_CLIENT_PORT"):
        os.environ["DEVSHELL_CLIENT_PORT"] = candidate_ports[0]

    chosen_cfg = os.environ.get("CLOUDSDK_CONFIG")
    if not chosen_cfg or not Path(chosen_cfg).is_dir():
        if candidate_configs:
            chosen_cfg = candidate_configs[0]
            os.environ["CLOUDSDK_CONFIG"] = chosen_cfg

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        for cfg in candidate_configs:
            adc_path = Path(cfg) / "application_default_credentials.json"
            if adc_path.is_file():
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_path)
                break
        else:
            if candidate_adcs:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = candidate_adcs[0]


def get_gcloud_identity_token(
    explicit_token: str | None = None,
    gcloud_account: str | None = None,
    force_refresh: bool = False,
) -> str:
    """Retrieve a GCP Identity Token via explicit token, env var, gcloud CLI, or ADC."""
    global _cached_token, _token_timestamp

    if explicit_token:
        return explicit_token.strip()

    env_token = os.environ.get("ID_TOKEN") or os.environ.get("BEARER_TOKEN")
    if env_token and not force_refresh:
        return env_token.strip()

    now = time.time()
    if not force_refresh and _cached_token and (now - _token_timestamp) < _TOKEN_TTL_SECONDS:
        return _cached_token

    _sync_cloudshell_auth_env(force=force_refresh)

    uid = os.getuid()
    cfg_candidates: list[str | None] = [os.environ.get("CLOUDSDK_CONFIG")]
    tmp_root = Path("/tmp")
    if tmp_root.is_dir():
        for td in sorted(
            tmp_root.glob("tmp.*"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
            reverse=True,
        ):
            try:
                if td.is_dir() and td.stat().st_uid == uid and (td / "credentials.db").is_file():
                    if str(td) not in cfg_candidates:
                        cfg_candidates.append(str(td))
            except Exception:
                pass
    home_cfg = str(Path.home() / ".config" / "gcloud")
    if home_cfg not in cfg_candidates:
        cfg_candidates.append(home_cfg)

    account = gcloud_account or os.environ.get("GCLOUD_ACCOUNT")
    cmds = [["gcloud", "auth", "print-identity-token"]]
    if account:
        cmds.append(["gcloud", "auth", "print-identity-token", f"--account={account}"])

    last_err: Exception | None = None
    for cfg_dir in cfg_candidates:
        env_copy = os.environ.copy()
        if cfg_dir:
            env_copy["CLOUDSDK_CONFIG"] = cfg_dir
        for cmd in cmds:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                    env=env_copy,
                )
                token = result.stdout.strip()
                if token:
                    if cfg_dir:
                        os.environ["CLOUDSDK_CONFIG"] = cfg_dir
                        adc_path = Path(cfg_dir) / "application_default_credentials.json"
                        if adc_path.is_file():
                            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_path)
                    _cached_token = token
                    _token_timestamp = now
                    return token
            except Exception as exc:
                last_err = exc

    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())
        adc_id_token = getattr(creds, "id_token", None)
        if adc_id_token and isinstance(adc_id_token, str) and adc_id_token.strip():
            _cached_token = adc_id_token.strip()
            _token_timestamp = now
            return _cached_token
    except Exception as exc:
        if last_err is None:
            last_err = exc

    raise RuntimeError(
        f"Failed to obtain GCP identity token via gcloud or ADC: {last_err}"
    ) from last_err


def _build_auth_headers(
    auth_cfg: dict[str, Any],
    explicit_token: str | None = None,
    force_refresh: bool = False,
) -> dict[str, str]:
    """Build HTTP authentication headers based on configured auth mode."""
    mode = str(auth_cfg.get("mode") or "none").lower()
    if mode == "none":
        return {}

    if mode == "gcloud-id-token":
        token = get_gcloud_identity_token(
            explicit_token=explicit_token,
            gcloud_account=auth_cfg.get("gcloud_account"),
            force_refresh=force_refresh,
        )
        return {"Authorization": f"bearer {token}"}

    if mode == "bearer-env":
        token_env = str(auth_cfg.get("token_env") or "BEARER_TOKEN")
        token = explicit_token or os.environ.get(token_env)
        if not token:
            raise RuntimeError(
                f"Auth mode 'bearer-env' requires --token or env var ${token_env}."
            )
        return {"Authorization": f"Bearer {token.strip()}"}

    if mode == "header-env":
        header_name = str(auth_cfg.get("header_name") or "X-API-Key")
        token_env = str(auth_cfg.get("token_env") or "API_KEY")
        val = explicit_token or os.environ.get(token_env)
        if not val:
            raise RuntimeError(
                f"Auth mode 'header-env' requires --token or env var ${token_env}."
            )
        return {header_name: val.strip()}

    raise ValueError(f"Unsupported auth mode: {mode}")


def _detect_gcp_project() -> str | None:
    """Detect default GCP project ID from environment or gcloud config."""
    for env_key in ("GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GCP_PROJECT"):
        val = os.environ.get(env_key)
        if val and val.strip():
            return val.strip()
    try:
        res = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        proj = res.stdout.strip()
        if proj and proj != "(unset)":
            return proj
    except Exception:
        pass
    return None


def _get_judge_client(judge_cfg: dict[str, Any]) -> Any:
    """Create or refresh a standalone google.genai.Client for LLM-as-a-Judge."""
    global _judge_client, _judge_client_created_at
    now = time.time()
    if _judge_client is not None and (now - _judge_client_created_at) <= _JUDGE_CLIENT_TTL_SECONDS:
        return _judge_client

    from google import genai  # type: ignore

    backend = str(judge_cfg.get("backend") or "auto").lower()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if backend == "api-key" or (backend == "auto" and api_key and not judge_cfg.get("project_id")):
        if not api_key:
            raise RuntimeError(
                "Judge backend 'api-key' requires GEMINI_API_KEY or GOOGLE_API_KEY."
            )
        _judge_client = genai.Client(api_key=api_key)
    else:
        _sync_cloudshell_auth_env()
        project_id = judge_cfg.get("project_id") or _detect_gcp_project()
        location = judge_cfg.get("location") or DEFAULT_JUDGE_LOCATION
        if not project_id:
            raise RuntimeError(
                "Vertex AI judge requires --project-id, judge.project_id in config, "
                "or GOOGLE_CLOUD_PROJECT / gcloud default project."
            )
        _judge_client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )

    _judge_client_created_at = now
    return _judge_client


def _load_adapter(adapter_path: Path | None) -> Any:
    """Dynamically load an optional Python adapter module for bespoke agent APIs."""
    if not adapter_path:
        return None
    if not adapter_path.is_file():
        raise FileNotFoundError(f"Adapter file not found: {adapter_path}")
    spec = importlib.util.spec_from_file_location("uat_custom_adapter", str(adapter_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load adapter module from {adapter_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_request_body(
    history_turns: list[dict[str, str]],
    question: str,
    req_cfg: dict[str, Any],
    adapter: Any = None,
) -> dict[str, Any]:
    """Construct the JSON request payload for the target AI agent endpoint."""
    if adapter is not None and hasattr(adapter, "build_request"):
        return adapter.build_request(history_turns, question, req_cfg)

    fmt = str(req_cfg.get("format") or "gemini-contents").lower()
    extra_body = req_cfg.get("extra_body") or {}

    if fmt == "gemini-contents":
        contents: list[dict[str, Any]] = []
        for turn in history_turns:
            contents.append({"role": "user", "parts": [{"text": turn["question"]}]})
            contents.append({"role": "model", "parts": [{"text": turn["answer"]}]})
        contents.append({"role": "user", "parts": [{"text": question}]})
        body: dict[str, Any] = {"contents": contents}
    elif fmt == "openai-messages":
        messages: list[dict[str, str]] = []
        for turn in history_turns:
            messages.append({"role": "user", "content": turn["question"]})
            messages.append({"role": "assistant", "content": turn["answer"]})
        messages.append({"role": "user", "content": question})
        body = {"messages": messages}
    elif fmt == "simple-chat":
        body = {
            "question": question,
            "history": [
                {"user": t["question"], "assistant": t["answer"]} for t in history_turns
            ],
        }
    else:
        raise ValueError(
            f"Unsupported request.format '{fmt}'. "
            "Use 'gemini-contents', 'openai-messages', 'simple-chat', or --adapter."
        )

    if isinstance(extra_body, dict):
        body.update(extra_body)
    return body


def _parse_json_payload(
    payload: Any,
    resp_cfg: dict[str, Any],
    answer_parts: list[str],
    sources: list[Any],
) -> str | None:
    """Extract text, sources, and error from a single decoded JSON payload."""
    text_field = str(resp_cfg.get("text_field") or "text")
    sources_field = str(resp_cfg.get("sources_field") or "sources")
    error_field = str(resp_cfg.get("error_field") or "error")

    stream_error: str | None = None
    if isinstance(payload, dict):
        err_val = _extract_path(payload, error_field)
        if err_val:
            stream_error = str(err_val)

        txt_val = _extract_path(payload, text_field)
        if txt_val is not None and txt_val != "":
            answer_parts.append(str(txt_val))

        src_val = _extract_path(payload, sources_field)
        if isinstance(src_val, list):
            for src in src_val:
                if src and src not in sources:
                    sources.append(src)
    else:
        answer_parts.append(str(payload))
    return stream_error


async def execute_turn(
    history_turns: list[dict[str, str]],
    question: str,
    client: httpx.AsyncClient,
    config: dict[str, Any],
    explicit_token: str | None = None,
    adapter: Any = None,
    max_retries: int = 8,
) -> dict[str, Any]:
    """Execute one conversation turn against the configured agent endpoint with retries."""
    endpoint_url = str(config["endpoint"])
    auth_cfg = config.get("auth") or {}
    req_cfg = config.get("request") or {}
    resp_cfg = config.get("response") or {}
    resp_mode = str(resp_cfg.get("mode") or "sse").lower()
    extra_headers = req_cfg.get("extra_headers") or {}

    request_body = _build_request_body(history_turns, question, req_cfg, adapter=adapter)

    for attempt in range(max_retries):
        answer_parts: list[str] = []
        sources: list[Any] = []
        stream_error: str | None = None

        try:
            headers = {"Content-Type": "application/json"}
            headers.update(_build_auth_headers(auth_cfg, explicit_token=explicit_token))
            if isinstance(extra_headers, dict):
                headers.update({str(k): str(v) for k, v in extra_headers.items()})

            if resp_mode == "json":
                response = await client.post(endpoint_url, headers=headers, json=request_body)
                if response.status_code == 401 and auth_cfg.get("mode") == "gcloud-id-token" and not explicit_token:
                    _build_auth_headers(auth_cfg, explicit_token=None, force_refresh=True)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                if response.status_code != 200:
                    stream_error = f"HTTP {response.status_code}: {response.text.strip()}"
                else:
                    raw_json = response.json()
                    if adapter is not None and hasattr(adapter, "parse_response"):
                        parsed = adapter.parse_response(raw_json)
                        return {"raw_response": parsed, "error": parsed.get("error")}
                    stream_error = _parse_json_payload(raw_json, resp_cfg, answer_parts, sources)
            else:
                async with client.stream(
                    "POST", endpoint_url, headers=headers, json=request_body
                ) as response:
                    if response.status_code == 401 and auth_cfg.get("mode") == "gcloud-id-token" and not explicit_token:
                        _build_auth_headers(auth_cfg, explicit_token=None, force_refresh=True)
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2.0 * (attempt + 1))
                            continue
                    if response.status_code != 200:
                        err_body = (await response.aread()).decode("utf-8", errors="replace")
                        stream_error = f"HTTP {response.status_code}: {err_body.strip()}"
                    else:
                        raw_lines: list[str] = []
                        async for raw_line in response.aiter_lines():
                            line = raw_line.strip()
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith("data:"):
                                line = line[len("data:") :].strip()
                                if not line or line == "[DONE]":
                                    continue
                            if adapter is not None and hasattr(adapter, "parse_response"):
                                raw_lines.append(line)
                                continue
                            try:
                                payload = json.loads(line)
                                err = _parse_json_payload(payload, resp_cfg, answer_parts, sources)
                                if err:
                                    stream_error = err
                            except json.JSONDecodeError:
                                answer_parts.append(line)

                        if adapter is not None and hasattr(adapter, "parse_response"):
                            parsed = adapter.parse_response(raw_lines)
                            return {"raw_response": parsed, "error": parsed.get("error")}
        except Exception as exc:
            stream_error = str(exc) or exc.__class__.__name__

        if (
            stream_error
            and any(marker in stream_error for marker in RETRYABLE_ERROR_MARKERS)
            and attempt < max_retries - 1
        ):
            await asyncio.sleep(min(45.0, 4.0 * (attempt + 1) + random.uniform(1.0, 4.0)))
            continue

        raw_response: dict[str, Any] = {
            "text": "".join(answer_parts).strip(),
            "sources": sources,
        }
        if stream_error:
            raw_response["error"] = stream_error
        return {"raw_response": raw_response, "error": stream_error}

    return {
        "raw_response": {"text": "", "sources": [], "error": "Max retries exceeded"},
        "error": "Max retries exceeded",
    }


def _normalize_item_turns(item: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize a multi-turn ('turns' list) or single-turn ('question') test item."""
    raw_turns = item.get("turns")
    normalized: list[dict[str, str]] = []
    if isinstance(raw_turns, list):
        for t in raw_turns:
            if not isinstance(t, dict):
                continue
            q = (t.get("question") or "").strip()
            if not q:
                continue
            normalized.append(
                {
                    "question": q,
                    "expected_answer": str(t.get("expected_answer") or ""),
                    "expected_behavior": str(t.get("expected_behavior") or ""),
                }
            )
        return normalized

    q = (item.get("question") or "").strip()
    if q:
        normalized.append(
            {
                "question": q,
                "expected_answer": str(item.get("expected_answer") or ""),
                "expected_behavior": str(item.get("expected_behavior") or ""),
            }
        )
    return normalized


def _aggregate_conversation_review(
    turn_records: list[dict[str, Any]],
    evaluate: bool = True,
) -> dict[str, Any]:
    """Aggregate per-turn uat_review objects into a conversation-level summary."""
    if not evaluate or not turn_records:
        return {"status": "PENDING_REVIEW", "score": 0.0, "comment": ""}

    statuses = [
        str((t.get("uat_review") or {}).get("status", "PENDING_REVIEW")).upper()
        for t in turn_records
    ]
    scores = [float((t.get("uat_review") or {}).get("score", 0.0)) for t in turn_records]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    total_turns = len(turn_records)
    pass_turns = sum(1 for s in statuses if s == "PASS")

    if all(s == "PASS" for s in statuses):
        return {
            "status": "PASS",
            "score": avg_score,
            "comment": f"All {total_turns}/{total_turns} turns passed.",
        }

    for target_status in ("FAIL", "PARTIAL"):
        if any(s == target_status for s in statuses):
            notes = [
                f"Turn {t.get('turn', idx)}: {(t.get('uat_review') or {}).get('comment', target_status)}"
                for idx, t in enumerate(turn_records, 1)
                if str((t.get("uat_review") or {}).get("status", "")).upper() == target_status
            ]
            return {
                "status": target_status,
                "score": avg_score,
                "comment": f"Passed {pass_turns}/{total_turns} turns. " + " | ".join(notes),
            }

    return {"status": "PENDING_REVIEW", "score": avg_score, "comment": ""}


async def evaluate_turn_result(
    record: dict[str, Any],
    history: list[dict[str, Any]] | None,
    agent_name: str,
    judge_cfg: dict[str, Any],
    domain_rubric: str = "",
    max_retries: int = 8,
) -> dict[str, Any]:
    """Evaluate a single UAT turn using Gemini LLM-as-a-Judge with structured JSON output."""
    raw_resp = record.get("raw_response") or {}
    exec_err = record.get("error") or raw_resp.get("error")
    if exec_err:
        return {
            "status": "FAIL",
            "score": 0.0,
            "behavior_check": f"FAIL - Execution error: {exec_err}",
            "answer_check": "FAIL - No answer generated due to error.",
            "comment": "Runtime or API error during question execution.",
        }

    from google.genai import types  # type: ignore

    client = _get_judge_client(judge_cfg)
    judge_model = str(judge_cfg.get("model") or DEFAULT_JUDGE_MODEL)

    sources = raw_resp.get("sources") or []
    gm = raw_resp.get("grounding_metadata") or {}
    g_chunks = gm.get("grounding_chunks") or []
    rag_summary = []
    for gc in g_chunks:
        rc = (gc.get("retrieved_context") if isinstance(gc, dict) else None) or {}
        if rc:
            rag_summary.append(
                {
                    "title": rc.get("title", ""),
                    "text_snippet": (rc.get("text") or "")[:600],
                }
            )

    history_block = ""
    if history:
        lines = []
        for h in history:
            t_num = h.get("turn", "?")
            h_raw = h.get("raw_response") or {}
            lines.append(f"- **Turn {t_num} User**: {h.get('question', '')}")
            lines.append(f"- **Turn {t_num} Assistant**: {h_raw.get('text', '')}")
        history_block = "### Prior Conversation History\n" + "\n".join(lines) + "\n\n"

    domain_block = ""
    if domain_rubric.strip():
        domain_block = f"\n### Domain-Specific Evaluation Rules\n{domain_rubric.strip()}\n"

    actual_answer = raw_resp.get("text", "")
    grounding_info = (
        json.dumps(rag_summary, ensure_ascii=False)
        if rag_summary
        else json.dumps({"streamed_sources": sources}, ensure_ascii=False)
    )

    eval_prompt = f"""You are a strict UAT QA Evaluator for {agent_name}.
Evaluate the following UAT conversation turn by comparing `actual_answer` (and its citations/grounding) against `expected_answer` and `expected_behavior`, taking into account any prior conversation history.

{history_block}### Current UAT Turn to Evaluate
- **ID**: {record.get("id")}
- **Turn**: {record.get("turn", 1)}
- **Question**: {record.get("question")}
- **Expected Answer**: {record.get("expected_answer") or "(None specified - rely on Expected Behavior)"}
- **Expected Behavior**: {record.get("expected_behavior") or "(None specified - rely on Expected Answer)"}
- **Actual Answer**:
{actual_answer}
- **Retrieved Sources / Grounding Info**: {grounding_info}

### Core Evaluation Guidelines
1. **Behavior Check (`behavior_check`)**:
   - Verify `actual_answer` obeys all positive requirements and negative constraints in `expected_behavior` (language/tone, multi-turn context retention, citation formatting, refusal/scope rules, and no hallucinated or fabricated facts).
   - Start with `"PASS - ..."` or `"FAIL - ..."`.
2. **Answer Check (`answer_check`)**:
   - Verify `actual_answer` conveys the core substance required by `expected_answer` (or `expected_behavior` when `expected_answer` is blank).
   - Start with `"PASS - ..."`, `"PARTIAL - ..."`, or `"FAIL - ..."`.
3. **Overall Status (`status`) and Score (`score`)**:
   - `"PASS"` (`score`: `1.0`): Both `behavior_check` and `answer_check` are `PASS`.
   - `"PARTIAL"` (`score`: `0.5`): `behavior_check` is `PASS` and `answer_check` is `PARTIAL` (minor non-hallucinatory omission).
   - `"FAIL"` (`score`: `0.0`): Either `behavior_check` is `FAIL` or `answer_check` is `FAIL`.
{domain_block}
Return a JSON object with keys: `status` ("PASS", "PARTIAL", or "FAIL"), `score` (1.0, 0.5, or 0.0), `behavior_check`, `answer_check`, and `comment` (a concise 1-sentence summary).
"""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "status": {"type": "STRING", "enum": ["PASS", "PARTIAL", "FAIL"]},
            "score": {"type": "NUMBER"},
            "behavior_check": {"type": "STRING"},
            "answer_check": {"type": "STRING"},
            "comment": {"type": "STRING"},
        },
        "required": ["status", "score", "behavior_check", "answer_check", "comment"],
    }

    score_map = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0}
    last_err = ""
    for attempt in range(max_retries):
        try:
            resp = await client.aio.models.generate_content(
                model=judge_model,
                contents=eval_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.0,
                ),
            )
            parsed = json.loads(resp.text or "{}")
            status = str(parsed.get("status", "FAIL")).upper()
            return {
                "status": status,
                "score": score_map.get(status, 0.0),
                "behavior_check": str(parsed.get("behavior_check", "")),
                "answer_check": str(parsed.get("answer_check", "")),
                "comment": str(parsed.get("comment", "")),
            }
        except Exception as exc:
            last_err = str(exc) or exc.__class__.__name__
            if any(m in last_err for m in RETRYABLE_ERROR_MARKERS) and attempt < max_retries - 1:
                await asyncio.sleep(min(45.0, 4.0 * (attempt + 1) + random.uniform(1.0, 4.0)))
                continue
            break

    return {
        "status": "FAIL",
        "score": 0.0,
        "behavior_check": f"FAIL - Judge error: {last_err}",
        "answer_check": "FAIL - Evaluation did not complete.",
        "comment": f"LLM-as-a-Judge error: {last_err}",
    }


def _open_eval_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _load_db_suite_inputs(
    db_path: Path, suite_id: str
) -> tuple[list[dict[str, Any]], dict[str, dict[int, dict[str, Any]]]]:
    """Load eval cases and prior latest turn results from SQLite DB."""
    conn = _open_eval_db(db_path)
    try:
        case_rows = conn.execute(
            """
            SELECT case_id, turns_json
            FROM eval_cases
            WHERE suite_id = ?
            ORDER BY sort_order ASC, case_id ASC
            """,
            (suite_id,),
        ).fetchall()
        questions: list[dict[str, Any]] = []
        for row in case_rows:
            turns = json.loads(row["turns_json"] or "[]")
            questions.append({"id": row["case_id"], "turns": turns})

        cached: dict[str, dict[int, dict[str, Any]]] = {}
        res_rows = conn.execute(
            "SELECT case_id, result_json FROM eval_latest_results WHERE suite_id = ?",
            (suite_id,),
        ).fetchall()
        for row in res_rows:
            try:
                rec = json.loads(row["result_json"] or "{}")
            except json.JSONDecodeError:
                continue
            t_map = {
                int(tr["turn"]): tr
                for tr in (rec.get("turns") or [])
                if isinstance(tr, dict) and isinstance(tr.get("turn"), int)
            }
            if t_map:
                cached[str(row["case_id"])] = t_map
        return questions, cached
    finally:
        conn.close()


def _write_case_result_db(
    db_path: Path,
    suite_id: str,
    job_id: str | None,
    record: dict[str, Any],
) -> None:
    """Incrementally persist a single finished case result into SQLite in O(1)."""
    now = time.time()
    cid = str(record.get("id") or "")
    rev = record.get("uat_review") or {}
    status = str(rev.get("status") or "PENDING_REVIEW").upper()
    score = float(rev.get("score") or 0.0)
    comment = str(rev.get("comment") or "")
    res_json = json.dumps(record, ensure_ascii=False)

    conn = _open_eval_db(db_path)
    try:
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
                (job_id, suite_id, cid, status, score, comment, res_json, now),
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
            (suite_id, cid, job_id, status, score, comment, res_json, now),
        )
        conn.commit()
    finally:
        conn.close()


def _load_cached_turns(
    target_turn: int | None,
    from_results: Path | None,
    default_output: Path | None,
) -> dict[str, dict[int, dict[str, Any]]]:
    """Load prior turns from an existing results JSON when --turn replay is active."""
    cached: dict[str, dict[int, dict[str, Any]]] = {}
    if target_turn is None or target_turn <= 1:
        return cached
    cache_path = from_results or (default_output if (default_output and default_output.is_file()) else None)
    if not cache_path or not cache_path.is_file():
        return cached
    try:
        cached_list = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached_list, list):
            for rec in cached_list:
                cid = str(rec.get("id", ""))
                t_map = {
                    tr["turn"]: tr
                    for tr in (rec.get("turns") or [])
                    if isinstance(tr, dict) and isinstance(tr.get("turn"), int)
                }
                if cid and t_map:
                    cached[cid] = t_map
    except Exception as exc:
        print(f"Warning: could not load cached turns from {cache_path}: {exc}")
    return cached


async def run_batch(
    input_path: Path | None,
    output_path: Path | None,
    config: dict[str, Any],
    explicit_token: str | None = None,
    filter_id: str | None = None,
    limit: int | None = None,
    evaluate: bool = True,
    domain_rubric: str = "",
    target_turn: int | None = None,
    from_results: Path | None = None,
    adapter: Any = None,
    *,
    db_path: Path | None = None,
    suite_id: str | None = None,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run all filtered eval conversations concurrently and write results to SQLite DB or JSON."""
    if db_path and suite_id:
        questions_data, db_cached = _load_db_suite_inputs(db_path, suite_id)
        cached_turns_by_id = db_cached if (target_turn is not None and target_turn > 1) else {}
    else:
        if not input_path or not input_path.is_file():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        questions_data = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(questions_data, list):
            raise ValueError("Input JSON must be a list of question objects.")
        cached_turns_by_id = _load_cached_turns(target_turn, from_results, output_path)

    if filter_id:
        allowed_ids = {s.strip() for s in str(filter_id).split(",") if s.strip()}
        questions_data = [q for q in questions_data if str(q.get("id")) in allowed_ids]

    if limit is not None and limit > 0:
        questions_data = questions_data[:limit]

    # Validate auth and judge client upfront before launching concurrent workers
    _build_auth_headers(config.get("auth") or {}, explicit_token=explicit_token)
    judge_cfg = config.get("judge") or {}
    if evaluate:
        _get_judge_client(judge_cfg)

    agent_name = str(config.get("agent_name") or "AI Agent")
    endpoint_url = str(config["endpoint"])
    concurrency = max(1, int(config.get("concurrency") or DEFAULT_CONCURRENCY))
    timeout_s = float(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    judge_model = str(judge_cfg.get("model") or DEFAULT_JUDGE_MODEL)
    total = len(questions_data)

    print("=" * 80)
    print(f"{agent_name} - Concurrent Eval Batch Runner")
    print(f"Endpoint URL: {endpoint_url}")
    if db_path and suite_id:
        print(f"SQLite Suite: {suite_id} ({total} cases) in {db_path}")
    else:
        print(f"Input File  : {input_path} ({total} conversations)")
        print(f"Output File : {output_path}")
    print(f"Concurrency : {concurrency} parallel worker(s)")
    print(
        f"LLM Eval    : {f'ENABLED (judge={judge_model})' if evaluate else 'DISABLED (--no-eval)'}"
    )
    if domain_rubric.strip():
        print("Domain Rules: LOADED")
    if target_turn is not None:
        print(f"Target Turn : Turn {target_turn} (replaying earlier turns from cache)")
    print("=" * 80)

    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    results_by_index: dict[int, dict[str, Any]] = {}

    timeout_cfg = httpx.Timeout(connect=30.0, read=timeout_s, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout_cfg) as http_client:

        async def _process_item(idx: int, item: dict[str, Any]) -> None:
            q_id = item.get("id", f"Q-{idx:03d}")
            turns = _normalize_item_turns(item)
            if not turns:
                print(f"[{idx}/{total}] Skipping {q_id}: no valid turns found.")
                return

            async with semaphore:
                print(f"\n[{idx}/{total}] Starting {q_id} ({len(turns)} turn(s))")
                t0 = time.perf_counter()

                history_turns: list[dict[str, str]] = []
                turn_records: list[dict[str, Any]] = []
                cached_map = cached_turns_by_id.get(str(q_id), {})

                for t_idx, turn in enumerate(turns, 1):
                    if target_turn is not None and t_idx > target_turn:
                        break

                    question = turn["question"]
                    if target_turn is not None and t_idx < target_turn and t_idx in cached_map:
                        cached_tr = cached_map[t_idx]
                        cached_text = (cached_tr.get("raw_response") or {}).get("text", "")
                        history_turns.append({"question": question, "answer": cached_text})
                        turn_records.append(cached_tr)
                        continue

                    exec_data = await execute_turn(
                        history_turns=list(history_turns),
                        question=question,
                        client=http_client,
                        config=config,
                        explicit_token=explicit_token,
                        adapter=adapter,
                    )
                    raw_response = exec_data["raw_response"]
                    history_turns.append(
                        {"question": question, "answer": raw_response.get("text", "")}
                    )

                    turn_record: dict[str, Any] = {
                        "turn": t_idx,
                        "question": question,
                        "raw_response": raw_response,
                        "expected_answer": turn["expected_answer"],
                        "expected_behavior": turn["expected_behavior"],
                        "uat_review": {
                            "status": "PENDING_REVIEW",
                            "score": 0.0,
                            "behavior_check": "",
                            "answer_check": "",
                            "comment": "",
                        },
                    }

                    if evaluate:
                        eval_input = dict(turn_record)
                        eval_input["id"] = f"{q_id} (Turn {t_idx})"
                        turn_record["uat_review"] = await evaluate_turn_result(
                            record=eval_input,
                            history=list(turn_records),
                            agent_name=agent_name,
                            judge_cfg=judge_cfg,
                            domain_rubric=domain_rubric,
                        )

                    turn_records.append(turn_record)

                elapsed = round(time.perf_counter() - t0, 2)
                conv_review = _aggregate_conversation_review(turn_records, evaluate=evaluate)
                record = {"id": q_id, "uat_review": conv_review, "turns": turn_records}

                async with write_lock:
                    results_by_index[idx] = record
                    if db_path and suite_id:
                        _write_case_result_db(db_path, suite_id, job_id, record)
                    elif output_path:
                        ordered_partial = [
                            results_by_index[k] for k in sorted(results_by_index.keys())
                        ]
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_text(
                            json.dumps(ordered_partial, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )

                print(
                    f"[{idx}/{total}] Finished {q_id} ({len(turn_records)} turn(s)) in {elapsed}s | "
                    f"Eval: {conv_review.get('status')} (score={conv_review.get('score')})"
                )
                for tr in turn_records:
                    t_num = tr["turn"]
                    t_rev = tr["uat_review"]
                    tr_raw = tr.get("raw_response") or {}
                    ans_preview = (tr_raw.get("text") or "").replace("\n", " ")[:90]
                    if tr_raw.get("error"):
                        print(f"  -> [{q_id} T{t_num}] ERROR: {tr_raw['error']}")
                    else:
                        print(
                            f"  -> [{q_id} T{t_num}] ({t_rev.get('status')}) "
                            f"Q: {tr['question'][:50]} | A: {ans_preview}..."
                        )
                        if evaluate and t_rev.get("comment"):
                            print(f"     Review: {t_rev.get('comment')}")

        batch_t0 = time.perf_counter()
        tasks = [
            asyncio.create_task(_process_item(idx, item))
            for idx, item in enumerate(questions_data, 1)
        ]
        if tasks:
            await asyncio.gather(*tasks)

    batch_elapsed = round(time.perf_counter() - batch_t0, 2)
    ordered_results = [results_by_index[k] for k in sorted(results_by_index.keys())]

    dest_label = f"SQLite suite '{suite_id}'" if (db_path and suite_id) else str(output_path)
    print("\n" + "=" * 80)
    print(
        f"Completed {len(ordered_results)}/{total} cases in {batch_elapsed}s "
        f"(concurrency={concurrency}). Saved to: {dest_label}"
    )
    if evaluate and ordered_results:
        pass_cnt = sum(1 for r in ordered_results if (r.get("uat_review") or {}).get("status") == "PASS")
        partial_cnt = sum(1 for r in ordered_results if (r.get("uat_review") or {}).get("status") == "PARTIAL")
        fail_cnt = sum(1 for r in ordered_results if (r.get("uat_review") or {}).get("status") == "FAIL")
        total_score = sum(float((r.get("uat_review") or {}).get("score", 0.0)) for r in ordered_results)
        pct = round((total_score / len(ordered_results)) * 100, 1)
        print(
            f"Evaluation Summary: PASS={pass_cnt}, PARTIAL={partial_cnt}, FAIL={fail_cnt} | "
            f"Total Score: {total_score}/{len(ordered_results)} ({pct}%)"
        )
    print("=" * 80)
    return ordered_results


def _load_config(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    """Merge SQLite suite config or optional JSON config file with CLI overrides and domain rubric."""
    cfg: dict[str, Any] = {
        "agent_name": "AI Agent",
        "endpoint": "",
        "auth": {"mode": "none"},
        "request": {"format": "gemini-contents"},
        "response": {"mode": "sse", "text_field": "text", "sources_field": "sources", "error_field": "error"},
        "judge": {"backend": "auto", "model": DEFAULT_JUDGE_MODEL, "location": DEFAULT_JUDGE_LOCATION},
        "concurrency": DEFAULT_CONCURRENCY,
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    }
    config_dir = Path.cwd()
    domain_rubric = ""

    if args.db and args.suite_id:
        conn = _open_eval_db(args.db)
        try:
            row = conn.execute(
                "SELECT config_json, rubric_md, name FROM eval_suites WHERE id = ?",
                (args.suite_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"Eval suite '{args.suite_id}' not found in {args.db}")
            user_cfg = json.loads(row["config_json"] or "{}")
            if isinstance(user_cfg, dict):
                for key, val in user_cfg.items():
                    if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                        cfg[key].update(val)
                    else:
                        cfg[key] = val
            if not cfg.get("agent_name") or cfg["agent_name"] == "AI Agent":
                cfg["agent_name"] = row["name"] or "AI Agent"
            domain_rubric = row["rubric_md"] or ""
        finally:
            conn.close()
    elif args.config:
        if not args.config.is_file():
            raise FileNotFoundError(f"Config file not found: {args.config}")
        config_dir = args.config.resolve().parent
        user_cfg = json.loads(args.config.read_text(encoding="utf-8"))
        for key, val in user_cfg.items():
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(val)
            else:
                cfg[key] = val

    # Apply CLI overrides
    if args.agent_name:
        cfg["agent_name"] = args.agent_name
    if args.endpoint:
        cfg["endpoint"] = args.endpoint
    if args.auth_mode:
        cfg["auth"]["mode"] = args.auth_mode
    if args.gcloud_account:
        cfg["auth"]["gcloud_account"] = args.gcloud_account
    if args.request_format:
        cfg["request"]["format"] = args.request_format
    if args.response_mode:
        cfg["response"]["mode"] = args.response_mode
    if args.concurrency is not None:
        cfg["concurrency"] = args.concurrency
    if args.project_id:
        cfg["judge"]["project_id"] = args.project_id
    if args.judge_location:
        cfg["judge"]["location"] = args.judge_location
    if args.judge_model:
        cfg["judge"]["model"] = args.judge_model

    if not cfg.get("endpoint"):
        raise ValueError("Missing endpoint URL. Configure 'endpoint' on the Eval Suite or pass --endpoint.")

    rubric_path = args.rubric
    if not rubric_path and cfg["judge"].get("rubric_file"):
        rp = Path(cfg["judge"]["rubric_file"])
        cand = rp if rp.is_absolute() else (config_dir / rp)
        if cand.is_file():
            rubric_path = cand

    if rubric_path:
        if not rubric_path.is_file():
            raise FileNotFoundError(f"Rubric file not found: {rubric_path}")
        domain_rubric = rubric_path.read_text(encoding="utf-8")

    return cfg, domain_rubric


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic multi-turn concurrent Eval batch runner with Gemini LLM-as-a-Judge."
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to ask_workbench.db SQLite store")
    parser.add_argument("--suite-id", type=str, default=None, help="Eval suite ID inside --db")
    parser.add_argument("--job-id", type=str, default=None, help="Optional eval_runs job_id for run history")
    parser.add_argument("--config", type=Path, default=None, help="Path to eval config JSON (legacy mode)")
    parser.add_argument("--input", "-i", type=Path, default=None, help="Input eval questions JSON (legacy mode)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output results JSON (legacy mode)")
    parser.add_argument("--endpoint", "--url", dest="endpoint", type=str, default=None, help="Agent chat endpoint URL")
    parser.add_argument("--agent-name", type=str, default=None, help="Display name of the agent under test")
    parser.add_argument("--auth-mode", choices=["none", "gcloud-id-token", "bearer-env", "header-env"], default=None, help="Endpoint auth mode")
    parser.add_argument("--gcloud-account", type=str, default=None, help="Optional gcloud account for identity token")
    parser.add_argument("--token", type=str, default=None, help="Explicit Bearer/API token override")
    parser.add_argument("--request-format", choices=["gemini-contents", "openai-messages", "simple-chat"], default=None, help="Request payload preset")
    parser.add_argument("--response-mode", choices=["sse", "json"], default=None, help="Response parsing mode")
    parser.add_argument("--adapter", type=Path, default=None, help="Optional Python adapter with build_request()/parse_response()")
    parser.add_argument("--rubric", type=Path, default=None, help="Optional markdown file with domain-specific judge rules")
    parser.add_argument("--id", type=str, default=None, help="Comma-separated case IDs to run (e.g. Q1,E003)")
    parser.add_argument("--turn", type=int, default=None, help="Run only up to turn N, replaying earlier turns from DB or --from-results")
    parser.add_argument("--from-results", type=Path, default=None, help="Prior results JSON for --turn replay (legacy mode)")
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N test cases")
    parser.add_argument("--concurrency", "-c", type=int, default=None, help=f"Parallel workers (default: {DEFAULT_CONCURRENCY})")
    parser.add_argument("--project-id", type=str, default=None, help="GCP Project ID for Vertex AI judge")
    parser.add_argument("--judge-location", type=str, default=None, help=f"Vertex AI location (default: {DEFAULT_JUDGE_LOCATION})")
    parser.add_argument("--judge-model", type=str, default=None, help=f"Judge model ID (default: {DEFAULT_JUDGE_MODEL})")
    parser.add_argument("--no-eval", action="store_true", help="Skip LLM-as-a-Judge evaluation")
    parser.add_argument("--runs", "-n", type=int, default=1, help="Number of sequential batch iterations for variance testing")

    args = parser.parse_args()
    if not (args.db and args.suite_id) and not args.input:
        parser.error("Provide either (--db and --suite-id) or -i/--input JSON path.")
    if not args.db and not args.output:
        args.output = Path("eval_results.json")

    config, domain_rubric = _load_config(args)
    adapter = _load_adapter(args.adapter)

    async def _run_all() -> None:
        total_runs = max(1, args.runs)
        run_summaries: list[tuple[int, float, int]] = []
        for run_idx in range(1, total_runs + 1):
            run_out = (
                args.output.with_name(f"{args.output.stem}_run{run_idx}{args.output.suffix}")
                if (args.output and total_runs > 1)
                else args.output
            )
            if total_runs > 1:
                print(f"\n==================== STARTING RUN {run_idx} / {total_runs} ====================")
            results = await run_batch(
                input_path=args.input,
                output_path=run_out,
                config=config,
                explicit_token=args.token,
                filter_id=args.id,
                limit=args.limit,
                evaluate=not args.no_eval,
                domain_rubric=domain_rubric,
                target_turn=args.turn,
                from_results=args.from_results,
                adapter=adapter,
                db_path=args.db,
                suite_id=args.suite_id,
                job_id=args.job_id,
            )
            if total_runs > 1:
                if args.output and not args.db:
                    args.output.write_text(
                        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                if not args.no_eval and results:
                    score = sum(float((r.get("uat_review") or {}).get("score", 0.0)) for r in results)
                    run_summaries.append((run_idx, score, len(results)))

        if len(run_summaries) > 1:
            print("\n" + "=" * 80)
            print(f"MULTI-RUN STABILITY SUMMARY ({len(run_summaries)} runs)")
            for idx, score, total in run_summaries:
                print(f"  Run {idx}: {score}/{total} ({round(score / total * 100, 1)}%)")
            avg = sum(s / t for _, s, t in run_summaries) / len(run_summaries) * 100
            print(f"  Mean Score: {round(avg, 1)}%")
            print("=" * 80)

    asyncio.run(_run_all())


if __name__ == "__main__":
    main()
