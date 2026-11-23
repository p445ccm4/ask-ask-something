"use client";

import React, { useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  FlaskConical,
  Play,
  RefreshCw,
  Search,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import type { UatCaseResult, UatOverview } from "@/lib/types";
import { MarkdownContent } from "@ag-workbench/index";

interface UatDashboardProps {
  workspaceId: string;
  overview: UatOverview | null;
  loading: boolean;
  runningLogs: string[];
  isUatRunning: boolean;
  onRefresh: () => void;
  onStartRun: (req: {
    case_ids?: string;
    turn?: number;
    runs?: number;
  }) => Promise<void>;
  onDiagnoseCase: (prompt: string, shouldFix: boolean) => void;
}

function StatusBadge({ status }: { status?: string }) {
  const norm = (status || "UNKNOWN").toUpperCase();
  if (norm === "PASS") {
    return (
      <span className="inline-flex select-none items-center gap-1 rounded bg-bea-emerald/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-bea-teal">
        <CheckCircle2 className="h-3 w-3 text-bea-emerald" />
        PASS
      </span>
    );
  }
  if (norm === "PARTIAL") {
    return (
      <span className="inline-flex select-none items-center gap-1 rounded bg-solar-yellow/25 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-bea-burgundy">
        <AlertCircle className="h-3 w-3 text-solar-orange" />
        PARTIAL
      </span>
    );
  }
  if (norm === "FAIL") {
    return (
      <span className="inline-flex select-none items-center gap-1 rounded bg-bea-coral/30 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-bea-burgundy">
        <XCircle className="h-3 w-3 text-solar-red" />
        FAIL
      </span>
    );
  }
  return (
    <span className="inline-flex select-none items-center rounded bg-bea-canvas px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-bea-text-secondary">
      PENDING
    </span>
  );
}

export function UatDashboard({
  workspaceId,
  overview,
  loading,
  runningLogs,
  isUatRunning,
  onRefresh,
  onStartRun,
  onDiagnoseCase,
}: UatDashboardProps) {
  const [statusFilter, setStatusFilter] = useState<"ALL" | "FAIL" | "PARTIAL" | "PASS">("ALL");
  const [search, setSearch] = useState("");
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});
  const [showConsole, setShowConsole] = useState(false);

  const displayCases: UatCaseResult[] = useMemo(() => {
    if (!overview) return [];
    if (overview.results.length > 0) return overview.results;
    return overview.questions.map((q) => ({
      id: q.id,
      uat_review: { status: "PENDING" },
      turns: q.turns.map((t, idx) => ({
        turn: idx + 1,
        question: t.question,
        expected_answer: t.expected_answer,
        expected_behavior: t.expected_behavior,
      })),
    }));
  }, [overview]);

  const filteredCases = useMemo(() => {
    const q = search.trim().toLowerCase();
    return displayCases.filter((item) => {
      const st = (item.uat_review?.status || "PENDING").toUpperCase();
      if (statusFilter !== "ALL" && st !== statusFilter) return false;
      if (!q) return true;
      if (item.id.toLowerCase().includes(q)) return true;
      return item.turns.some(
        (t) =>
          t.question.toLowerCase().includes(q) ||
          (t.raw_response?.text || "").toLowerCase().includes(q) ||
          (t.uat_review?.comment || "").toLowerCase().includes(q)
      );
    });
  }, [displayCases, statusFilter, search]);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const buildPromptForCase = (item: UatCaseResult, shouldFix: boolean) => {
    const failingTurns = item.turns.filter(
      (t) => (t.uat_review?.status || "").toUpperCase() !== "PASS"
    );
    const focus = failingTurns.length > 0 ? failingTurns : item.turns;
    const summaryText = focus
      .map(
        (t) =>
          `Turn ${t.turn}: Q="${t.question}"\n` +
          `Status: ${t.uat_review?.status || "N/A"}\n` +
          `Judge Comment: ${t.uat_review?.comment || "N/A"}\n` +
          `Sources: ${(t.raw_response?.sources || []).join(", ") || "None"}`
      )
      .join("\n---\n");

    if (shouldFix) {
      return (
        `Diagnose and fix UAT case ${item.id}.\n` +
        `First inspect the full details via get_uat_case_detail(case_id="${item.id}") and search the repository code/prompts/RAG logic to find the root cause.\n` +
        `Then propose or apply a minimal fix, verify with targeted UAT/unit checks, and check git diff.\n\n` +
        `Context:\n${summaryText}`
      );
    }
    return (
      `Diagnose UAT case ${item.id} in read-only mode.\n` +
      `Call get_uat_case_detail(case_id="${item.id}"), inspect the relevant code/prompts/retrieval files in the repo, and explain the exact root cause and recommended fix.\n\n` +
      `Context:\n${summaryText}`
    );
  };

  const summary = overview?.summary;
  const endpoint =
    typeof overview?.config?.endpoint === "string"
      ? overview.config.endpoint
      : null;

  return (
    <section className="flex h-full min-h-0 flex-col bg-bea-canvas">
      {/* Top KPI & Actions Bar */}
      <div className="space-y-3 border-b border-bea-border bg-bea-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-neutral-800">UAT Suite Overview</h2>
            <p className="truncate text-[11px] text-bea-text-secondary">
              {endpoint ? (
                <>
                  Endpoint: <code className="text-bea-blue">{endpoint}</code>
                </>
              ) : (
                "No uat_config.json detected yet (read-only questions/results view)"
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs font-medium text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            {overview?.has_results && (
              <a
                href={`/api/workspaces/${encodeURIComponent(workspaceId)}/uat/export-csv`}
                className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs font-medium text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas"
              >
                <Download className="h-3.5 w-3.5" />
                CSV
              </a>
            )}
            <button
              type="button"
              disabled={
                isUatRunning ||
                !overview?.has_config ||
                !overview?.has_questions ||
                !summary?.failing_ids.length
              }
              onClick={() => {
                if (!summary?.failing_ids.length) return;
                setShowConsole(true);
                onStartRun({ case_ids: summary.failing_ids.join(",") });
              }}
              className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-solar-orange/50 bg-solar-yellow/20 px-2.5 py-1.5 text-xs font-semibold text-bea-burgundy shadow-2xs transition hover:bg-solar-yellow/35 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Play className="h-3.5 w-3.5 text-solar-red-orange" />
              Re-run Failing ({summary?.failing_ids.length ?? 0})
            </button>
            <button
              type="button"
              disabled={isUatRunning || !overview?.has_config || !overview?.has_questions}
              onClick={() => {
                setShowConsole(true);
                onStartRun({});
              }}
              className="white-on-solar inline-flex cursor-pointer items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold shadow-sm transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Play className="h-3.5 w-3.5" />
              {isUatRunning ? "Running UAT..." : "Run Full Suite"}
            </button>
          </div>
        </div>

        {/* Summary KPI Strip */}
        <div className="grid grid-cols-4 gap-2">
          <div className="rounded-xl border border-bea-border bg-bea-canvas/60 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-bea-text-secondary">
              Score
            </div>
            <div className="solar-on-white mt-0.5 text-base font-extrabold">
              {summary?.evaluated_cases ? `${summary.score_pct}%` : "—"}
            </div>
          </div>
          <div className="rounded-xl border border-bea-emerald/35 bg-bea-emerald/10 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-bea-teal">
              PASS
            </div>
            <div className="mt-0.5 text-base font-bold text-bea-teal">
              {summary?.pass_count ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-solar-orange/35 bg-solar-yellow/15 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-solar-red-orange">
              PARTIAL
            </div>
            <div className="mt-0.5 text-base font-bold text-bea-burgundy">
              {summary?.partial_count ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-solar-red/35 bg-bea-coral/25 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-solar-red">
              FAIL
            </div>
            <div className="mt-0.5 text-base font-bold text-bea-burgundy">
              {summary?.fail_count ?? 0}
            </div>
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-bea-border bg-bea-canvas p-0.5 text-[11px]">
            {(["ALL", "FAIL", "PARTIAL", "PASS"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setStatusFilter(tab)}
                className={`cursor-pointer rounded-md px-2.5 py-1 font-semibold transition ${
                  statusFilter === tab
                    ? "bg-bea-card text-neutral-900 shadow-xs"
                    : "text-bea-text-secondary hover:text-neutral-800"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-bea-text-secondary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search UAT ID, question, or judge review..."
              className="w-full rounded-lg border border-bea-border bg-bea-card py-1.5 pl-8 pr-3 text-xs text-neutral-800 placeholder-bea-text-secondary focus:border-solar-red focus:outline-none"
            />
          </div>
          {runningLogs.length > 0 && (
            <button
              type="button"
              onClick={() => setShowConsole((v) => !v)}
              className="cursor-pointer rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-[11px] font-semibold text-bea-blue shadow-2xs hover:bg-bea-canvas"
            >
              {showConsole ? "Hide Logs" : `Show Logs (${runningLogs.length})`}
            </button>
          )}
        </div>

        {showConsole && runningLogs.length > 0 && (
          <div className="max-h-44 overflow-auto rounded-xl border border-bea-border bg-neutral-900 p-3 font-mono text-[11px] leading-5 text-neutral-100">
            {runningLogs.map((ln, idx) => (
              <div key={idx} className="whitespace-pre-wrap">
                {ln}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Case List */}
      <div className="flex-1 space-y-2.5 overflow-y-auto p-4">
        {loading && !overview ? (
          <div className="py-12 text-center text-xs text-bea-text-secondary">
            Loading UAT suite...
          </div>
        ) : filteredCases.length === 0 ? (
          <div className="rounded-xl border border-dashed border-bea-border bg-bea-card p-6 text-center text-xs text-bea-text-secondary">
            {overview && !overview.has_questions && !overview.has_results ? (
              <div className="space-y-2">
                <p className="font-semibold text-neutral-800">
                  No UAT questions or results found in this workspace yet.
                </p>
                <p>
                  Ask the Antigravity agent on the right to onboard UAT testing for this repository or inspect its codebase directly.
                </p>
              </div>
            ) : (
              "No matching UAT cases for the current filter."
            )}
          </div>
        ) : (
          filteredCases.map((item) => {
            const isOpen = Boolean(expandedIds[item.id]);
            const firstQuestion = item.turns[0]?.question || "(No question)";
            return (
              <div
                key={item.id}
                className="rounded-xl border border-bea-border bg-bea-card shadow-2xs transition hover:border-solar-orange/60"
              >
                <div className="flex items-start justify-between gap-3 p-3.5">
                  <button
                    type="button"
                    onClick={() => toggleExpand(item.id)}
                    className="flex min-w-0 flex-1 cursor-pointer items-start gap-2 text-left"
                  >
                    {isOpen ? (
                      <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-bea-text-secondary" />
                    ) : (
                      <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-bea-text-secondary" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-solar-red">
                          {item.id}
                        </span>
                        <StatusBadge status={item.uat_review?.status} />
                        {typeof item.uat_review?.score === "number" && (
                          <span className="text-[11px] font-medium text-bea-text-secondary">
                            score={item.uat_review.score}
                          </span>
                        )}
                        <span className="text-[11px] text-bea-text-secondary">
                          {item.turns.length} turn{item.turns.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs font-medium text-neutral-800">
                        {firstQuestion}
                      </p>
                      {item.uat_review?.comment && !isOpen && (
                        <p className="mt-1 line-clamp-1 text-[11px] text-bea-text-secondary">
                          {item.uat_review.comment}
                        </p>
                      )}
                    </div>
                  </button>

                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => onDiagnoseCase(buildPromptForCase(item, false), false)}
                      title="Ask Antigravity agent to diagnose in Read-Only mode"
                      className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-blue/35 bg-bea-blue/5 px-2.5 py-1 text-[11px] font-semibold text-bea-blue shadow-2xs transition hover:bg-bea-blue/15"
                    >
                      <Sparkles className="h-3 w-3" />
                      Diagnose
                    </button>
                    <button
                      type="button"
                      onClick={() => onDiagnoseCase(buildPromptForCase(item, true), true)}
                      title="Ask Antigravity agent to diagnose & fix"
                      className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-solar-red/35 bg-bea-coral/20 px-2.5 py-1 text-[11px] font-semibold text-bea-burgundy shadow-2xs transition hover:bg-bea-coral/35"
                    >
                      <Wrench className="h-3 w-3 text-solar-red" />
                      Fix
                    </button>
                  </div>
                </div>

                {isOpen && (
                  <div className="animate-view-fade-in space-y-3 border-t border-bea-border bg-bea-canvas/45 p-3.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-[11px] text-bea-text-secondary">
                        {item.uat_review?.comment || ""}
                      </span>
                      {overview?.has_config && (
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            disabled={isUatRunning}
                            onClick={() => {
                              setShowConsole(true);
                              onStartRun({ case_ids: item.id });
                            }}
                            className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1 text-[11px] font-medium text-neutral-800 shadow-2xs hover:bg-bea-canvas disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <Play className="h-3 w-3 text-solar-red" />
                            Re-run {item.id}
                          </button>
                          <button
                            type="button"
                            disabled={isUatRunning}
                            onClick={() => {
                              setShowConsole(true);
                              onStartRun({ case_ids: item.id, runs: 5 });
                            }}
                            className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1 text-[11px] font-medium text-neutral-800 shadow-2xs hover:bg-bea-canvas disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            <FlaskConical className="h-3 w-3 text-bea-teal" />
                            5x Stability
                          </button>
                        </div>
                      )}
                    </div>

                    {item.turns.map((turn) => (
                      <div
                        key={turn.turn}
                        className="space-y-2 rounded-xl border border-bea-border bg-bea-card p-3 text-xs"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-neutral-800">
                            Turn {turn.turn}
                          </span>
                          <StatusBadge status={turn.uat_review?.status} />
                        </div>

                        <div>
                          <div className="text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                            Question
                          </div>
                          <div className="mt-0.5 whitespace-pre-wrap text-neutral-800">
                            {turn.question}
                          </div>
                        </div>

                        {turn.raw_response?.error && (
                          <div className="rounded-lg bg-bea-coral/25 p-2 text-bea-burgundy">
                            Error: {turn.raw_response.error}
                          </div>
                        )}

                        {turn.raw_response?.text && (
                          <div>
                            <div className="text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                              Actual Answer
                            </div>
                            <div className="mt-0.5 max-h-56 overflow-y-auto rounded-lg border border-bea-border bg-bea-canvas/55 p-2.5">
                              <MarkdownContent content={turn.raw_response.text} />
                            </div>
                          </div>
                        )}

                        {turn.raw_response?.sources && turn.raw_response.sources.length > 0 && (
                          <div>
                            <div className="text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                              Retrieved Sources
                            </div>
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {turn.raw_response.sources.map((src, i) => (
                                <span
                                  key={i}
                                  className="select-text rounded bg-bea-canvas px-2 py-0.5 font-mono text-[10px] text-bea-teal"
                                >
                                  {src}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="grid grid-cols-1 gap-2 pt-1 md:grid-cols-2">
                          {turn.expected_answer && (
                            <div>
                              <div className="text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                                Expected Answer
                              </div>
                              <div className="mt-0.5 max-h-36 overflow-y-auto whitespace-pre-wrap rounded-lg border border-bea-border bg-bea-canvas/40 p-2 text-[11px] text-bea-text-primary">
                                {turn.expected_answer}
                              </div>
                            </div>
                          )}
                          {turn.expected_behavior && (
                            <div>
                              <div className="text-[10px] font-semibold uppercase tracking-wide text-bea-text-secondary">
                                Expected Behavior
                              </div>
                              <div className="mt-0.5 max-h-36 overflow-y-auto whitespace-pre-wrap rounded-lg border border-bea-border bg-bea-canvas/40 p-2 text-[11px] text-bea-text-primary">
                                {turn.expected_behavior}
                              </div>
                            </div>
                          )}
                        </div>

                        {(turn.uat_review?.behavior_check || turn.uat_review?.answer_check) && (
                          <div className="space-y-1 rounded-lg border border-bea-border bg-bea-canvas/55 p-2.5 text-[11px] text-bea-text-primary">
                            {turn.uat_review.behavior_check && (
                              <div>
                                <span className="font-semibold text-neutral-800">
                                  Behavior Check:{" "}
                                </span>
                                {turn.uat_review.behavior_check}
                              </div>
                            )}
                            {turn.uat_review.answer_check && (
                              <div>
                                <span className="font-semibold text-neutral-800">
                                  Answer Check:{" "}
                                </span>
                                {turn.uat_review.answer_check}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
