"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Brain,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Loader2,
  MessageSquarePlus,
  Send,
  Square,
  Terminal,
  User,
  Wrench,
  XCircle,
} from "lucide-react";
import type {
  ChatMessage,
  ConversationRecord,
  ExecutionMode,
  ModelOption,
  ToolEvent,
} from "@/lib/types";
import { ApprovalCard } from "./ApprovalCard";
import { MarkdownContent } from "./MarkdownContent";

interface AgentWorkbenchProps {
  workspaceName: string;
  mode: ExecutionMode;
  availableModels: ModelOption[];
  selectedModel: string;
  onSelectModel: (modelId: string) => void;
  conversations: ConversationRecord[];
  activeConversationId: string;
  messages: ChatMessage[];
  streaming: boolean;
  onSelectConversation: (convId: string) => void;
  onNewConversation: () => void;
  onSendMessage: (message: string) => Promise<void>;
  onStopStreaming: () => void;
  onDecideApproval: (approvalId: string, approved: boolean) => Promise<void>;
}

interface GroupedToolStep {
  key: string;
  name: string;
  args?: Record<string, unknown>;
  result?: string;
  error?: string | null;
  hasResult: boolean;
}

function groupToolEvents(events: ToolEvent[]): GroupedToolStep[] {
  const steps: GroupedToolStep[] = [];
  const openById = new Map<string, GroupedToolStep>();
  const openByName: GroupedToolStep[] = [];

  events.forEach((ev, idx) => {
    if (ev.type === "tool_call") {
      const step: GroupedToolStep = {
        key: ev.id || `step-${idx}`,
        name: ev.name,
        args: ev.args,
        hasResult: false,
      };
      steps.push(step);
      if (ev.id) openById.set(ev.id, step);
      openByName.push(step);
    } else {
      let target: GroupedToolStep | undefined;
      if (ev.id && openById.has(ev.id)) {
        target = openById.get(ev.id);
        openById.delete(ev.id);
      } else {
        target = [...openByName]
          .reverse()
          .find((s) => !s.hasResult && s.name === ev.name);
      }
      if (target) {
        target.result = ev.result;
        target.error = ev.error;
        target.hasResult = true;
      } else {
        steps.push({
          key: ev.id || `res-${idx}`,
          name: ev.name,
          result: ev.result,
          error: ev.error,
          hasResult: true,
        });
      }
    }
  });

  return steps;
}

function strArg(args: Record<string, unknown> | undefined, ...keys: string[]): string {
  if (!args) return "";
  for (const k of keys) {
    const val = args[k];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return "";
}

function summarizeToolCall(
  name: string,
  args?: Record<string, unknown>
): { summary: string; consumedKeys: Set<string> } {
  const consumedKeys = new Set<string>(["WaitMsBeforeAsync", "wait_ms"]);
  if (!args) return { summary: "", consumedKeys };

  if (name === "view_file" || name === "edit_file" || name === "create_file") {
    const file = strArg(args, "TargetFile", "target_file", "file_path", "path", "AbsolutePath");
    consumedKeys.add("TargetFile");
    consumedKeys.add("target_file");
    consumedKeys.add("file_path");
    consumedKeys.add("path");
    consumedKeys.add("AbsolutePath");
    const start = args.StartLine ?? args.start_line;
    const end = args.EndLine ?? args.end_line;
    if (start !== undefined) consumedKeys.add("StartLine");
    if (start !== undefined) consumedKeys.add("start_line");
    if (end !== undefined) consumedKeys.add("EndLine");
    if (end !== undefined) consumedKeys.add("end_line");
    const lineRange =
      start !== undefined && end !== undefined
        ? ` (L${start}-L${end})`
        : start !== undefined
        ? ` (from L${start})`
        : "";
    return { summary: file ? `${file}${lineRange}` : "", consumedKeys };
  }

  if (name === "list_directory") {
    const dir = strArg(args, "DirectoryPath", "directory_path", "path");
    consumedKeys.add("DirectoryPath");
    consumedKeys.add("directory_path");
    consumedKeys.add("path");
    return { summary: dir || ".", consumedKeys };
  }

  if (name === "search_directory") {
    const query = strArg(args, "Query", "query", "pattern");
    const searchPath = strArg(args, "SearchPath", "search_path", "path");
    consumedKeys.add("Query");
    consumedKeys.add("query");
    consumedKeys.add("pattern");
    consumedKeys.add("SearchPath");
    consumedKeys.add("search_path");
    consumedKeys.add("path");
    return {
      summary: query ? `"${query}"${searchPath ? ` in ${searchPath}` : ""}` : searchPath,
      consumedKeys,
    };
  }

  if (name === "find_file") {
    const pattern = strArg(args, "Pattern", "pattern");
    const dir = strArg(args, "SearchDirectory", "search_directory", "path");
    consumedKeys.add("Pattern");
    consumedKeys.add("pattern");
    consumedKeys.add("SearchDirectory");
    consumedKeys.add("search_directory");
    consumedKeys.add("path");
    return {
      summary: pattern ? `"${pattern}"${dir ? ` in ${dir}` : ""}` : dir,
      consumedKeys,
    };
  }

  if (name === "run_command") {
    const cmd = strArg(args, "CommandLine", "command_line", "command");
    const cwd = strArg(args, "Cwd", "cwd");
    consumedKeys.add("CommandLine");
    consumedKeys.add("command_line");
    consumedKeys.add("command");
    consumedKeys.add("Cwd");
    consumedKeys.add("cwd");
    return {
      summary: cmd ? `$ ${cmd}` : cwd,
      consumedKeys,
    };
  }

  if (name === "get_uat_case_detail") {
    const caseId = strArg(args, "case_id");
    consumedKeys.add("case_id");
    return { summary: caseId ? `Case ${caseId}` : "", consumedKeys };
  }

  if (name === "run_uat_check") {
    const caseIds = strArg(args, "case_ids");
    const runs = typeof args.runs === "number" ? args.runs : undefined;
    consumedKeys.add("case_ids");
    consumedKeys.add("runs");
    const base = caseIds ? `Cases: ${caseIds}` : "Full UAT suite";
    return { summary: runs && runs > 1 ? `${base} (${runs}x)` : base, consumedKeys };
  }

  if (name === "get_uat_summary") {
    return { summary: "Workspace UAT overview", consumedKeys };
  }

  if (name === "get_git_diff") {
    return { summary: "Scoped git diff", consumedKeys };
  }

  return { summary: "", consumedKeys };
}

function getInformativeArgs(
  name: string,
  args: Record<string, unknown> | undefined,
  consumedKeys: Set<string>
): Record<string, unknown> | null {
  if (!args) return null;
  const filtered: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(args)) {
    if (consumedKeys.has(k)) continue;
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    if (name === "run_uat_check" && k === "runs" && v === 1) continue;
    filtered[k] = v;
  }
  return Object.keys(filtered).length > 0 ? filtered : null;
}

function formatToolOutput(text?: string): string {
  if (!text) return "";
  const trimmed = text.trim();
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      return text;
    }
  }
  return text;
}

function ToolTimeline({
  events,
  isStreaming,
}: {
  events: ToolEvent[];
  isStreaming?: boolean;
}) {
  const steps = useMemo(() => groupToolEvents(events), [events]);
  if (!steps.length) return null;

  const counts = new Map<string, number>();
  for (const st of steps) {
    counts.set(st.name, (counts.get(st.name) || 0) + 1);
  }
  const breakdown = Array.from(counts.entries())
    .map(([name, count]) => (count > 1 ? `${name} ×${count}` : name))
    .join(", ");

  const activeStep =
    isStreaming && !steps[steps.length - 1]?.hasResult
      ? steps[steps.length - 1]
      : null;
  const errorCount = steps.filter((s) => Boolean(s.error)).length;

  return (
    <details className="group/tools my-2 rounded-lg border border-bea-border bg-bea-canvas/55 text-xs">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-lg px-3 py-2 text-[11px] font-medium text-neutral-800 transition hover:bg-bea-canvas">
        <div className="flex min-w-0 items-center gap-2">
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-bea-text-secondary transition-transform group-open/tools:rotate-90" />
          {activeStep ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-solar-red" />
          ) : errorCount > 0 ? (
            <XCircle className="h-3.5 w-3.5 shrink-0 text-solar-red" />
          ) : (
            <Wrench className="h-3.5 w-3.5 shrink-0 text-bea-teal" />
          )}
          <span className="shrink-0 font-semibold text-neutral-800">
            {activeStep
              ? `Running ${activeStep.name}...`
              : `Used ${steps.length} tool${steps.length === 1 ? "" : "s"}`}
          </span>
          <span className="truncate font-mono text-[10px] text-bea-text-secondary">
            {breakdown}
          </span>
        </div>
        <span className="shrink-0 text-[10px] font-medium text-bea-blue group-open/tools:hidden">
          Inspect
        </span>
        <span className="hidden shrink-0 text-[10px] font-medium text-bea-text-secondary group-open/tools:inline">
          Collapse
        </span>
      </summary>

      <div className="space-y-1.5 border-t border-bea-border/80 bg-bea-card/60 p-2">
        {steps.map((step, idx) => {
          const isCmd = step.name === "run_command";
          const isActive =
            Boolean(isStreaming) && idx === steps.length - 1 && !step.hasResult;
          const isDone = step.hasResult || !isStreaming || idx < steps.length - 1;
          const { summary, consumedKeys } = summarizeToolCall(step.name, step.args);
          const extraArgs = getInformativeArgs(step.name, step.args, consumedKeys);
          const formattedOutput = step.error || formatToolOutput(step.result);
          const hasDetails = Boolean(extraArgs || formattedOutput);

          const statusIcon = step.error ? (
            <XCircle className="h-3 w-3 shrink-0 text-solar-red" />
          ) : isActive ? (
            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-solar-orange" />
          ) : isDone ? (
            <CheckCircle2 className="h-3 w-3 shrink-0 text-bea-emerald" />
          ) : isCmd ? (
            <Terminal className="h-3 w-3 shrink-0 text-bea-teal" />
          ) : (
            <Wrench className="h-3 w-3 shrink-0 text-bea-teal" />
          );

          if (!hasDetails) {
            return (
              <div
                key={step.key}
                className="flex items-center justify-between gap-2 rounded-md border border-bea-border/70 bg-bea-card px-2.5 py-1.5 text-[11px]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  {statusIcon}
                  <code className="shrink-0 font-semibold text-bea-teal">
                    {step.name}
                  </code>
                  {summary && (
                    <span className="truncate font-mono text-[11px] text-bea-text-primary">
                      {summary}
                    </span>
                  )}
                </div>
                {isDone && !step.error && (
                  <span className="shrink-0 text-[10px] text-bea-text-secondary">
                    done
                  </span>
                )}
              </div>
            );
          }

          return (
            <details
              key={step.key}
              className="group/step rounded-md border border-bea-border/80 bg-bea-card text-[11px]"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md px-2.5 py-1.5 hover:bg-bea-canvas/60">
                <div className="flex min-w-0 items-center gap-2">
                  <ChevronRight className="h-3 w-3 shrink-0 text-bea-text-secondary transition-transform group-open/step:rotate-90" />
                  {statusIcon}
                  <code className="shrink-0 font-semibold text-bea-teal">
                    {step.name}
                  </code>
                  {summary && (
                    <span className="truncate font-mono text-[11px] text-bea-text-primary">
                      {summary}
                    </span>
                  )}
                </div>
                <span className="shrink-0 text-[10px] text-bea-text-secondary">
                  {step.error ? "error" : isActive ? "running" : "details"}
                </span>
              </summary>

              <div className="space-y-2 border-t border-bea-border/70 bg-bea-canvas/40 p-2.5">
                {extraArgs && (
                  <div>
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                      Parameters
                    </div>
                    <pre className="max-h-40 overflow-auto rounded border border-bea-border bg-bea-card p-2 font-mono text-[11px] text-bea-text-primary">
                      {JSON.stringify(extraArgs, null, 2)}
                    </pre>
                  </div>
                )}
                {formattedOutput && (
                  <div>
                    <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                      {step.error ? "Error Output" : "Output"}
                    </div>
                    <pre
                      className={`max-h-52 overflow-auto whitespace-pre-wrap rounded border p-2 font-mono text-[11px] ${
                        step.error
                          ? "border-solar-red/40 bg-bea-coral/15 text-bea-burgundy"
                          : "border-bea-border bg-bea-card text-bea-text-primary"
                      }`}
                    >
                      {formattedOutput}
                    </pre>
                  </div>
                )}
              </div>
            </details>
          );
        })}
      </div>
    </details>
  );
}

export function AgentWorkbench({
  workspaceName,
  mode,
  availableModels,
  selectedModel,
  onSelectModel,
  conversations,
  activeConversationId,
  messages,
  streaming,
  onSelectConversation,
  onNewConversation,
  onSendMessage,
  onStopStreaming,
  onDecideApproval,
}: AgentWorkbenchProps) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft("");
    await onSendMessage(text);
  };

  const quickPrompts = [
    "Summarize the current UAT pass/fail status and main failure patterns.",
    "Inspect the system prompt and RAG retrieval code in this repository.",
    "Show the current uncommitted git diff for this service.",
  ];

  return (
    <section className="flex h-full min-h-0 flex-col bg-bea-canvas">
      {/* Top Conversation Controls */}
      <div className="flex items-center justify-between gap-2 border-b border-bea-border bg-bea-card px-4 py-3">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-solar-red" />
          <h2 className="text-sm font-bold text-neutral-800">Antigravity Agent</h2>
          <span className="select-none rounded bg-bea-canvas px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
            {mode === "read_only"
              ? "Read-Only"
              : mode === "ask_before_fix"
              ? "Ask-Before-Fix"
              : "Sandboxed Auto"}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {conversations.length > 0 && (
            <select
              value={activeConversationId}
              onChange={(e) => onSelectConversation(e.target.value)}
              aria-label="Conversation session"
              className="max-w-[200px] cursor-pointer truncate rounded-lg border border-bea-border bg-bea-card px-2 py-1 text-xs font-medium text-neutral-800 focus:border-solar-red focus:outline-none"
            >
              {conversations.map((c) => (
                <option key={c.conversation_id} value={c.conversation_id}>
                  {c.title}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            disabled={streaming}
            onClick={onNewConversation}
            className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1 text-xs font-medium text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas disabled:cursor-not-allowed disabled:opacity-40"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
            New Chat
          </button>
        </div>
      </div>

      {/* Message Stream */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center space-y-4 text-center">
            <div className="max-w-md rounded-2xl border border-bea-border bg-bea-card p-6 shadow-xs">
              <div className="white-on-solar mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl shadow-sm">
                <Bot className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-bold text-neutral-800">
                Maintainer ready for {workspaceName}
              </h3>
              <p className="mt-1 text-xs text-bea-text-secondary">
                Inspect code, analyze failing UAT turns, apply sandboxed fixes, and verify regressions.
              </p>
              <div className="mt-4 space-y-1.5 text-left">
                {quickPrompts.map((qp) => (
                  <button
                    key={qp}
                    type="button"
                    onClick={() => onSendMessage(qp)}
                    className="block w-full cursor-pointer rounded-xl border border-bea-border bg-bea-canvas/60 px-3 py-2 text-xs text-bea-text-primary shadow-2xs transition hover:border-solar-orange hover:bg-bea-card hover:text-neutral-900"
                  >
                    {qp}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div
              key={idx}
              className={`animate-pill-fade flex gap-3 ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              {msg.role === "assistant" && (
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-bea-border bg-bea-card text-solar-red shadow-2xs">
                  <Bot className="h-4 w-4" />
                </div>
              )}

              <div
                className={`max-w-[88%] rounded-2xl px-4 py-3 text-xs leading-relaxed shadow-2xs ${
                  msg.role === "user"
                    ? "white-on-solar font-medium"
                    : "w-full border border-bea-border bg-bea-card text-bea-text-primary"
                }`}
              >
                {msg.role === "user" ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <div>
                    {msg.model && (
                      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium text-bea-text-secondary">
                        <Cpu className="h-3 w-3 text-bea-teal" />
                        <span>{msg.model}</span>
                      </div>
                    )}

                    {msg.thought && (
                      <details className="group/thought mb-2 rounded-lg border border-bea-border bg-bea-canvas/60 px-3 py-2">
                        <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[11px] font-semibold text-bea-text-secondary hover:text-neutral-800">
                          <ChevronRight className="h-3.5 w-3.5 transition-transform group-open/thought:rotate-90" />
                          <Brain className="h-3.5 w-3.5 text-solar-orange" />
                          <span>Antigravity Thinking</span>
                        </summary>
                        <div className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] text-bea-text-secondary">
                          {msg.thought}
                        </div>
                      </details>
                    )}

                    {msg.tool_events && msg.tool_events.length > 0 && (
                      <ToolTimeline
                        events={msg.tool_events}
                        isStreaming={Boolean(msg.streaming)}
                      />
                    )}

                    {msg.approvals &&
                      msg.approvals.map((appr) => (
                        <ApprovalCard
                          key={appr.approval_id}
                          approval={appr}
                          onDecide={onDecideApproval}
                        />
                      ))}

                    {msg.error && (
                      <div className="my-2 rounded-lg border border-solar-red/40 bg-bea-coral/25 p-2.5 text-xs text-bea-burgundy">
                        {msg.error}
                      </div>
                    )}

                    {msg.content ? (
                      <MarkdownContent content={msg.content} />
                    ) : msg.streaming ? (
                      <div className="flex items-center gap-2 py-1 text-bea-text-secondary">
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-solar-red" />
                        <span>Working...</span>
                      </div>
                    ) : null}

                    {msg.cancelled && (
                      <div className="mt-2 border-t border-bea-border/60 pt-1.5 text-[11px] font-medium text-bea-text-secondary">
                        Generation stopped by user.
                      </div>
                    )}
                  </div>
                )}
              </div>

              {msg.role === "user" && (
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-bea-border bg-bea-card text-bea-text-primary shadow-2xs">
                  <User className="h-4 w-4" />
                </div>
              )}
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>

      {/* Composer with Model Selector + Send/Stop */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-bea-border bg-bea-card p-3"
      >
        <div className="rounded-xl border border-bea-border bg-bea-card p-2 shadow-2xs focus-within:border-solar-red">
          <textarea
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            placeholder={`Ask Antigravity to inspect or fix ${workspaceName}... (Enter to send, Shift+Enter for newline)`}
            className="max-h-40 w-full resize-none bg-transparent px-2 py-1 text-xs text-neutral-800 placeholder-bea-text-secondary focus:outline-none"
          />

          <div className="mt-1.5 flex items-center justify-between gap-2 border-t border-bea-border/70 pt-2">
            <div className="flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5 text-bea-teal" />
              <label htmlFor="chat-model-select" className="sr-only">
                Select Model
              </label>
              <select
                id="chat-model-select"
                value={selectedModel}
                disabled={streaming}
                onChange={(e) => onSelectModel(e.target.value)}
                aria-label="Agent model selector"
                className="cursor-pointer rounded-lg border border-bea-border bg-bea-canvas/70 px-2 py-1 text-[11px] font-semibold text-neutral-800 transition hover:bg-bea-canvas focus:border-solar-red focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
              >
                {availableModels.map((m) => (
                  <option key={m.id || "auto"} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            {streaming ? (
              <button
                type="button"
                onClick={onStopStreaming}
                className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-solar-red px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs transition hover:bg-bea-burgundy"
              >
                <Square className="h-3 w-3 fill-current" />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim()}
                className="white-on-solar inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-semibold shadow-xs transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Send className="h-3.5 w-3.5" />
                <span>Send</span>
              </button>
            )}
          </div>
        </div>
      </form>
    </section>
  );
}
