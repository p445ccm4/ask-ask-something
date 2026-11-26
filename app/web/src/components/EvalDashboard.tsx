"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  Database,
  Download,
  FileSpreadsheet,
  FileText,
  FlaskConical,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { MarkdownContent } from "@ag-workbench/index";
import { apiUrl } from "@/lib/basePath";
import type {
  EnvName,
  EvalCaseDetail,
  EvalCaseSummary,
  EvalOverview,
  EvalRunRecord,
  EvalSuiteSummary,
} from "@/lib/types";

interface EvalDashboardProps {
  projectId: string;
  projectName: string;
  activeEnv: EnvName;
  activeSuiteId: string;
  overview: EvalOverview | null;
  overviewVersion: number;
  loading: boolean;
  runningLogs: string[];
  isEvalRunning: boolean;
  onSelectSuite: (suiteId: string) => void;
  onRefresh: () => void;
  onStartRun: (req: {
    suite_id?: string;
    case_ids?: string;
    turn?: number;
    runs?: number;
  }) => void;
  onDiagnoseCase: (prompt: string, shouldFix: boolean) => void;
  onOpenCreateSuite: () => void;
  onOpenEditSuite: (suiteId: string) => void;
  onOpenImportXlsx: () => void;
}

type StatusFilter = "ALL" | "FAIL" | "PARTIAL" | "PASS" | "PENDING";
type TurnFilter = "ALL" | "MULTI" | "SINGLE";
type SortBy = "ORDER" | "STATUS" | "ID";

function formatRelativeTime(epochSec: number | null | undefined): string {
  if (!epochSec) return "Never";
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - epochSec));
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function StatusBadge({ status }: { status?: string }) {
  const s = (status || "PENDING").toUpperCase();
  if (s === "PASS") {
    return (
      <span className="inline-flex items-center rounded-md border border-bea-emerald/40 bg-bea-emerald/15 px-2 py-0.5 text-[11px] font-bold text-bea-teal">
        PASS
      </span>
    );
  }
  if (s === "PARTIAL") {
    return (
      <span className="inline-flex items-center rounded-md border border-solar-orange/45 bg-solar-yellow/20 px-2 py-0.5 text-[11px] font-bold text-solar-red-orange">
        PARTIAL
      </span>
    );
  }
  if (s === "FAIL") {
    return (
      <span className="inline-flex items-center rounded-md border border-solar-red/40 bg-bea-coral/35 px-2 py-0.5 text-[11px] font-bold text-bea-burgundy">
        FAIL
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md border border-bea-border bg-bea-canvas px-2 py-0.5 text-[11px] font-semibold text-bea-text-secondary">
      PENDING
    </span>
  );
}

export function EvalDashboard({
  projectId,
  projectName,
  activeEnv,
  activeSuiteId,
  overview,
  overviewVersion,
  loading,
  runningLogs,
  isEvalRunning,
  onSelectSuite,
  onRefresh,
  onStartRun,
  onDiagnoseCase,
  onOpenCreateSuite,
  onOpenEditSuite,
  onOpenImportXlsx,
}: EvalDashboardProps) {
  // Searchable suite selector state
  const [suiteDropdownOpen, setSuiteDropdownOpen] = useState(false);
  const [suiteSearch, setSuiteSearch] = useState("");
  const [suiteOptions, setSuiteOptions] = useState<EvalSuiteSummary[]>([]);
  const [suitesTotal, setSuitesTotal] = useState(0);
  const [suitesLoading, setSuitesLoading] = useState(false);
  const suiteDropdownRef = useRef<HTMLDivElement | null>(null);

  // Sidebar & filter state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [turnFilter, setTurnFilter] = useState<TurnFilter>("ALL");
  const [sortBy, setSortBy] = useState<SortBy>("ORDER");
  const [caseSearch, setCaseSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Cases list & pagination
  const [cases, setCases] = useState<EvalCaseSummary[]>([]);
  const [casesTotal, setCasesTotal] = useState(0);
  const [casesHasMore, setCasesHasMore] = useState(false);
  const [casesLoading, setCasesLoading] = useState(false);

  // Selected case detail
  const [selectedCaseId, setSelectedCaseId] = useState<string>("");
  const [caseDetail, setCaseDetail] = useState<EvalCaseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Logs & History modal
  const [logsModalOpen, setLogsModalOpen] = useState(false);
  const [selectedHistoricalRun, setSelectedHistoricalRun] = useState<{
    run: EvalRunRecord;
    lines: string[];
  } | null>(null);
  const [loadingRunLogs, setLoadingRunLogs] = useState(false);

  // Legacy import status
  const [importingLegacy, setImportingLegacy] = useState(false);
  const [legacyMessage, setLegacyMessage] = useState<string | null>(null);

  const summary = overview?.summary;
  const activeSuite = overview?.active_suite || null;
  const resolvedSuiteId = activeSuite?.id || activeSuiteId || "";

  // Sync initial cases when overview updates and no filters are overriding
  useEffect(() => {
    if (!overview) {
      setCases([]);
      setCasesTotal(0);
      setCasesHasMore(false);
      setSuiteOptions([]);
      setSuitesTotal(0);
      return;
    }
    setSuiteOptions(overview.suites || []);
    setSuitesTotal(overview.suites_total || 0);
  }, [overview]);

  // Reset filters & selection when project/env/suite changes
  useEffect(() => {
    setSelectedCaseId("");
    setCaseDetail(null);
    setLegacyMessage(null);
  }, [projectId, activeEnv, resolvedSuiteId]);

  // Debounce case search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(caseSearch.trim()), 220);
    return () => clearTimeout(t);
  }, [caseSearch]);

  // Close suite dropdown on outside click
  useEffect(() => {
    if (!suiteDropdownOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (
        suiteDropdownRef.current &&
        !suiteDropdownRef.current.contains(e.target as Node)
      ) {
        setSuiteDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [suiteDropdownOpen]);

  // Search suites when dropdown is open and user types
  useEffect(() => {
    if (!suiteDropdownOpen || !projectId) return;
    let active = true;
    const timer = setTimeout(async () => {
      setSuitesLoading(true);
      try {
        const params = new URLSearchParams({
          env: activeEnv,
          limit: "50",
          offset: "0",
        });
        if (suiteSearch.trim()) params.set("search", suiteSearch.trim());
        const res = await fetch(
          apiUrl(
            `/api/projects/${encodeURIComponent(
              projectId
            )}/eval/suites?${params.toString()}`
          )
        );
        if (!res.ok) return;
        const data = await res.json();
        if (active) {
          setSuiteOptions(data.suites || []);
          setSuitesTotal(data.total ?? 0);
        }
      } finally {
        if (active) setSuitesLoading(false);
      }
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [suiteDropdownOpen, suiteSearch, projectId, activeEnv]);

  // Query cases from SQLite whenever filters, search, sort, suite, or overviewVersion change
  const fetchCasesPage = useCallback(
    async (offset: number, append: boolean) => {
      if (!projectId || !resolvedSuiteId) {
        setCases([]);
        setCasesTotal(0);
        setCasesHasMore(false);
        return;
      }
      setCasesLoading(true);
      try {
        const params = new URLSearchParams({
          env: activeEnv,
          status: statusFilter,
          turn_filter: turnFilter,
          sort_by: sortBy,
          limit: "200",
          offset: String(offset),
        });
        if (debouncedSearch) params.set("search", debouncedSearch);
        const res = await fetch(
          apiUrl(
            `/api/projects/${encodeURIComponent(
              projectId
            )}/eval/suites/${encodeURIComponent(
              resolvedSuiteId
            )}/cases?${params.toString()}`
          )
        );
        if (!res.ok) return;
        const data = await res.json();
        const incoming: EvalCaseSummary[] = data.cases || [];
        setCases((prev) => (append ? [...prev, ...incoming] : incoming));
        setCasesTotal(data.total ?? incoming.length);
        setCasesHasMore(Boolean(data.has_more));
        if (!append) {
          setSelectedCaseId((curr) => {
            if (curr && incoming.some((c) => c.id === curr)) return curr;
            return incoming[0]?.id || "";
          });
        }
      } finally {
        setCasesLoading(false);
      }
    },
    [
      projectId,
      resolvedSuiteId,
      activeEnv,
      statusFilter,
      turnFilter,
      sortBy,
      debouncedSearch,
    ]
  );

  useEffect(() => {
    void fetchCasesPage(0, false);
  }, [fetchCasesPage, overviewVersion]);

  // Fetch full case detail when selectedCaseId or overviewVersion changes
  useEffect(() => {
    if (!projectId || !resolvedSuiteId || !selectedCaseId) {
      setCaseDetail(null);
      setDetailError(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError(null);
    fetch(
      apiUrl(
        `/api/projects/${encodeURIComponent(
          projectId
        )}/eval/suites/${encodeURIComponent(
          resolvedSuiteId
        )}/cases/${encodeURIComponent(selectedCaseId)}?env=${activeEnv}`
      )
    )
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to load case detail");
        return data.case as EvalCaseDetail;
      })
      .then((detail) => {
        if (active) setCaseDetail(detail);
      })
      .catch((err) => {
        if (active) setDetailError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [projectId, resolvedSuiteId, selectedCaseId, activeEnv, overviewVersion]);

  const buildPromptForCase = (detail: EvalCaseDetail, shouldFix: boolean) => {
    const status = detail.eval_review?.status || "PENDING";
    const comment = detail.eval_review?.comment || "";
    const firstQ = detail.turns[0]?.question || "";
    if (shouldFix) {
      return (
        `Fix failing Eval case ${detail.id} in project '${projectName}' (${activeEnv.toUpperCase()} environment, suite '${
          activeSuite?.name || resolvedSuiteId
        }'). ` +
        `Current status: ${status}. Judge note: "${comment}". Question: "${firstQ}". ` +
        `Use \`get_eval_case_detail(case_id="${detail.id}", env="${activeEnv}", suite_id="${resolvedSuiteId}")\` ` +
        `to inspect retrieved sources, expected answer/behavior, and actual answer; inspect the relevant code in the ${activeEnv.toUpperCase()} repo; apply a targeted fix; ` +
        `then run \`run_eval_check(case_ids="${detail.id}", env="${activeEnv}", suite_id="${resolvedSuiteId}")\` to verify. Do NOT write to scripts/uat/.`
      );
    }
    return (
      `Diagnose Eval case ${detail.id} in project '${projectName}' (${activeEnv.toUpperCase()} environment, suite '${
        activeSuite?.name || resolvedSuiteId
      }') in read-only mode. ` +
      `Current status: ${status}. Judge note: "${comment}". ` +
      `Call \`get_eval_case_detail(case_id="${detail.id}", env="${activeEnv}", suite_id="${resolvedSuiteId}")\` ` +
      `and inspect the ${activeEnv.toUpperCase()} codebase to identify root causes and propose concrete edits without modifying files.`
    );
  };

  const handleLoadHistoricalRun = async (run: EvalRunRecord) => {
    setLoadingRunLogs(true);
    try {
      const res = await fetch(
        apiUrl(`/api/eval/jobs/${encodeURIComponent(run.job_id)}`)
      );
      const data = await res.json();
      if (res.ok) {
        setSelectedHistoricalRun({ run, lines: data.lines || [] });
      }
    } finally {
      setLoadingRunLogs(false);
    }
  };

  const handleImportLegacy = async () => {
    if (!projectId) return;
    setImportingLegacy(true);
    setLegacyMessage(null);
    try {
      const res = await fetch(
        apiUrl(
          `/api/projects/${encodeURIComponent(
            projectId
          )}/eval/import-legacy?env=${activeEnv}&force=true`
        ),
        { method: "POST" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Legacy import failed");
      if (data.imported) {
        setLegacyMessage(
          `Imported ${data.cases_count} cases and ${data.results_count} results into SQLite DB.`
        );
        onSelectSuite(data.suite_id);
        onRefresh();
      } else {
        setLegacyMessage(`No legacy scripts/uat files found (${data.reason}).`);
      }
    } catch (err) {
      setLegacyMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setImportingLegacy(false);
    }
  };

  const failCount = summary?.fail_count ?? 0;
  const partialCount = summary?.partial_count ?? 0;
  const passCount = summary?.pass_count ?? 0;
  const totalCases = summary?.total_cases ?? 0;
  const evaluatedCases = summary?.evaluated_cases ?? 0;
  const failingIds = summary?.failing_ids || [];

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* MAIN SECTION COMMAND BAR (Eval Suite selector + Eval Score + KPI filters + Eval Actions) */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-bea-border bg-bea-surface-subtle px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          {/* Searchable Eval Suite Selector (100-500+ scale) */}
          <div className="relative" ref={suiteDropdownRef}>
            <button
              type="button"
              disabled={!projectId}
              onClick={() => setSuiteDropdownOpen((v) => !v)}
              title="Switch Eval Suite (searchable across 100-500+ suites)"
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-bea-border bg-bea-card px-3 py-1.5 text-xs font-bold text-bea-text-strong shadow-2xs transition hover:border-solar-red"
            >
              <Database className="h-3.5 w-3.5 text-solar-red" />
              <span className="max-w-[200px] truncate">
                {activeSuite?.name || "No Eval Suite"}
              </span>
              <span className="rounded bg-bea-canvas px-1.5 py-0.5 font-mono text-[10px] font-semibold text-bea-text-secondary">
                {suitesTotal} {suitesTotal === 1 ? "suite" : "suites"}
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-bea-text-secondary" />
            </button>

            {suiteDropdownOpen && (
              <div className="dropdown-menu absolute left-0 z-30 mt-1.5 w-80 p-2">
                <div className="relative mb-2">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-bea-text-secondary" />
                  <input
                    type="text"
                    autoFocus
                    value={suiteSearch}
                    onChange={(e) => setSuiteSearch(e.target.value)}
                    placeholder={`Search ${activeEnv.toUpperCase()} eval suites...`}
                    className="w-full rounded-lg border border-bea-border bg-bea-canvas py-1.5 pr-2.5 pl-8 text-xs text-bea-text-strong focus:border-solar-red focus:outline-none"
                  />
                </div>
                <div role="listbox" aria-label="Eval suites" className="max-h-64 space-y-1 overflow-y-auto">
                  {suitesLoading ? (
                    <div className="py-4 text-center text-xs text-bea-text-secondary">
                      Searching suites...
                    </div>
                  ) : suiteOptions.length === 0 ? (
                    <div className="py-4 text-center text-xs text-bea-text-secondary">
                      No matching eval suites in {activeEnv.toUpperCase()}.
                    </div>
                  ) : (
                    suiteOptions.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        role="option"
                        aria-selected={s.id === resolvedSuiteId}
                        onClick={() => {
                          onSelectSuite(s.id);
                          setSuiteDropdownOpen(false);
                        }}
                        className="dropdown-item flex-col items-start gap-0.5 py-2"
                      >
                        <div className="flex w-full items-center justify-between gap-2">
                          <span className="truncate font-bold">{s.name}</span>
                          <span className="shrink-0 font-mono text-[11px] font-bold text-bea-teal">
                            {s.evaluated_cases > 0 ? `${s.score_pct}%` : `${s.total_cases}c`}
                          </span>
                        </div>
                        <div className="flex w-full items-center justify-between gap-2 text-[10px] text-bea-text-secondary">
                          <span className="truncate font-mono">
                            {s.endpoint || "No endpoint"}
                          </span>
                          <span className="shrink-0">
                            {s.total_cases} cases
                          </span>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          <button
            type="button"
            disabled={!projectId}
            onClick={onOpenCreateSuite}
            title="Create new Eval Suite"
            className="btn btn-sm btn-secondary text-xs"
          >
            <Plus className="h-3.5 w-3.5 text-solar-red" />
            <span className="hidden xl:inline">New Suite</span>
          </button>

          {activeSuite && (
            <button
              type="button"
              onClick={() => onOpenEditSuite(activeSuite.id)}
              title="Configure Eval Suite endpoint, judge & domain rubric"
              className="btn btn-sm btn-secondary text-xs"
            >
              <Settings2 className="h-3.5 w-3.5 text-bea-text-secondary" />
              <span className="hidden xl:inline">Suite Config</span>
            </button>
          )}

          <div className="hidden h-5 w-px bg-bea-border sm:block" />

          {/* Eval Score Pill */}
          <div className="inline-flex items-center gap-2 rounded-lg border border-bea-border bg-bea-card px-3 py-1.5 text-xs font-extrabold shadow-2xs">
            <span className="font-semibold text-bea-text-secondary">
              Eval Score
            </span>
            <span className="text-solar-red">
              {evaluatedCases > 0 ? `${summary?.score_pct ?? 0}%` : "—"}
            </span>
            <span className="font-mono text-[11px] font-semibold text-bea-text-secondary">
              ({summary?.total_score ?? 0}/{evaluatedCases})
            </span>
          </div>

          {/* Clickable KPI Filter Pills */}
          <button
            type="button"
            onClick={() => setStatusFilter("ALL")}
            className={`cursor-pointer rounded-lg border px-2.5 py-1 text-xs font-bold transition ${
              statusFilter === "ALL"
                ? "border-solar-red bg-solar-red/10 text-solar-red"
                : "border-bea-border bg-bea-card text-bea-text-strong hover:bg-bea-canvas"
            }`}
          >
            All ({totalCases})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("PASS")}
            className={`cursor-pointer rounded-lg border px-2.5 py-1 text-xs font-bold transition ${
              statusFilter === "PASS"
                ? "border-bea-emerald bg-bea-emerald/15 text-bea-teal"
                : "border-bea-border bg-bea-card text-bea-teal hover:bg-bea-emerald/10"
            }`}
          >
            PASS {passCount}
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("PARTIAL")}
            className={`cursor-pointer rounded-lg border px-2.5 py-1 text-xs font-bold transition ${
              statusFilter === "PARTIAL"
                ? "border-solar-orange bg-solar-yellow/25 text-solar-red-orange"
                : "border-bea-border bg-bea-card text-solar-red-orange hover:bg-solar-yellow/15"
            }`}
          >
            PARTIAL {partialCount}
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter("FAIL")}
            className={`cursor-pointer rounded-lg border px-2.5 py-1 text-xs font-bold transition ${
              statusFilter === "FAIL"
                ? "border-solar-red bg-bea-coral/35 text-bea-burgundy"
                : "border-bea-border bg-bea-card text-bea-burgundy hover:bg-bea-coral/20"
            }`}
          >
            FAIL {failCount}
          </button>

          <span className="pl-1 text-[11px] text-bea-text-secondary">
            {isEvalRunning
              ? "Running eval..."
              : `Last eval: ${formatRelativeTime(overview?.results_updated_at)}`}
          </span>
        </div>

        {/* Right: Eval Actions */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="btn btn-sm btn-secondary text-xs"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setSelectedHistoricalRun(null);
              setLogsModalOpen(true);
            }}
            className="btn btn-sm btn-secondary text-xs"
          >
            <FileText className="h-3.5 w-3.5 text-bea-blue" />
            <span>Eval Logs</span>
            {isEvalRunning && (
              <span className="h-2 w-2 animate-pulse rounded-full bg-solar-orange" />
            )}
          </button>

          <button
            type="button"
            disabled={!projectId}
            onClick={onOpenImportXlsx}
            className="btn btn-sm btn-secondary text-xs"
          >
            <FileSpreadsheet className="h-3.5 w-3.5 text-bea-emerald" />
            <span>Import .xlsx</span>
          </button>

          {resolvedSuiteId && (
            <a
              href={apiUrl(
                `/api/projects/${encodeURIComponent(
                  projectId
                )}/eval/suites/${encodeURIComponent(
                  resolvedSuiteId
                )}/export-csv?env=${activeEnv}`
              )}
              download
              className="btn btn-sm btn-secondary text-xs"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Export CSV</span>
            </a>
          )}

          {resolvedSuiteId && overview?.has_template_xlsx && (
            <a
              href={apiUrl(
                `/api/projects/${encodeURIComponent(
                  projectId
                )}/eval/suites/${encodeURIComponent(
                  resolvedSuiteId
                )}/export-xlsx?env=${activeEnv}`
              )}
              download
              className="btn btn-sm btn-secondary text-xs"
            >
              <FileSpreadsheet className="h-3.5 w-3.5 text-bea-teal" />
              <span>Export .xlsx</span>
            </a>
          )}

          {overview?.has_config && failingIds.length > 0 && (
            <button
              type="button"
              disabled={isEvalRunning}
              onClick={() => {
                setLogsModalOpen(true);
                onStartRun({
                  suite_id: resolvedSuiteId,
                  case_ids: failingIds.join(","),
                });
              }}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-solar-orange px-3 py-1.5 text-xs font-bold text-white shadow-2xs transition hover:bg-solar-red-orange disabled:opacity-45"
            >
              <Play className="h-3.5 w-3.5" />
              Re-run Failing ({failingIds.length})
            </button>
          )}

          {overview?.has_config && overview?.has_questions && (
            <button
              type="button"
              disabled={isEvalRunning}
              onClick={() => {
                setLogsModalOpen(true);
                onStartRun({ suite_id: resolvedSuiteId });
              }}
              className="btn btn-sm btn-solar text-xs"
            >
              <Play className="h-3.5 w-3.5" />
              {isEvalRunning ? "Running..." : "Run Full Eval Suite"}
            </button>
          )}
        </div>
      </div>

      {/* MAIN BODY: Collapsible Left Sidebar + Right Case Detail Pane */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Left Collapsible Sidebar */}
        <aside
          className={`flex shrink-0 flex-col border-r border-bea-border bg-bea-surface-subtle transition-all duration-200 ${
            sidebarCollapsed ? "w-12" : "w-[330px]"
          }`}
        >
          <div
            className={`flex items-center border-b border-bea-border px-3 py-2.5 ${
              sidebarCollapsed ? "justify-center px-1" : "justify-between"
            }`}
          >
            {!sidebarCollapsed && (
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-extrabold text-bea-text-strong">
                  Eval Cases
                </span>
                <span className="rounded bg-bea-card px-1.5 py-0.5 font-mono text-[10px] font-bold text-bea-text-secondary">
                  {casesTotal}
                </span>
              </div>
            )}
            <button
              type="button"
              onClick={() => setSidebarCollapsed((v) => !v)}
              title={sidebarCollapsed ? "Expand cases sidebar" : "Collapse sidebar"}
              className="rounded-lg border border-bea-border bg-bea-card p-1 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
            >
              {sidebarCollapsed ? (
                <PanelLeftOpen className="h-3.5 w-3.5" />
              ) : (
                <PanelLeftClose className="h-3.5 w-3.5" />
              )}
            </button>
          </div>

          {sidebarCollapsed ? (
            <div className="flex flex-col items-center gap-2 py-3">
              {(
                [
                  ["ALL", totalCases, "text-bea-text-strong"],
                  ["FAIL", failCount, "text-bea-burgundy"],
                  ["PARTIAL", partialCount, "text-solar-red-orange"],
                  ["PASS", passCount, "text-bea-teal"],
                ] as const
              ).map(([st, cnt, colorCls]) => (
                <button
                  key={st}
                  type="button"
                  onClick={() => {
                    setStatusFilter(st);
                    setSidebarCollapsed(false);
                  }}
                  title={`${st}: ${cnt} (click to filter & expand)`}
                  className={`flex h-7 w-9 cursor-pointer items-center justify-center rounded-md border border-bea-border bg-bea-card font-mono text-[11px] font-extrabold ${colorCls} hover:border-solar-red`}
                >
                  {cnt}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              {/* Filters */}
              <div className="space-y-2 border-b border-bea-border p-3">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-bea-text-secondary" />
                  <input
                    type="text"
                    value={caseSearch}
                    onChange={(e) => setCaseSearch(e.target.value)}
                    placeholder="Search ID, question, judge comment..."
                    className="w-full rounded-lg border border-bea-border bg-bea-card py-1.5 pr-3 pl-8 text-xs text-bea-text-strong placeholder-bea-text-secondary focus:border-solar-red focus:outline-none"
                  />
                </div>

                <div className="flex flex-wrap gap-1">
                  {(["ALL", "FAIL", "PARTIAL", "PASS", "PENDING"] as const).map(
                    (tab) => (
                      <button
                        key={tab}
                        type="button"
                        onClick={() => setStatusFilter(tab)}
                        className={`cursor-pointer rounded-md border px-2 py-0.5 text-[11px] font-bold transition ${
                          statusFilter === tab
                            ? "border-solar-red bg-solar-red text-white"
                            : "border-bea-border bg-bea-card text-bea-text-secondary hover:text-bea-text-strong"
                        }`}
                      >
                        {tab}
                      </button>
                    )
                  )}
                </div>

                <div className="flex gap-1.5">
                  <select
                    value={turnFilter}
                    onChange={(e) => setTurnFilter(e.target.value as TurnFilter)}
                    aria-label="Turn filter"
                    className="flex-1 rounded-md border border-bea-border bg-bea-card px-2 py-1 text-[11px] font-medium text-bea-text-strong"
                  >
                    <option value="ALL">All turns</option>
                    <option value="MULTI">Multi-turn</option>
                    <option value="SINGLE">Single-turn</option>
                  </select>
                  <select
                    value={sortBy}
                    onChange={(e) => setSortBy(e.target.value as SortBy)}
                    aria-label="Sort order"
                    className="flex-1 rounded-md border border-bea-border bg-bea-card px-2 py-1 text-[11px] font-medium text-bea-text-strong"
                  >
                    <option value="ORDER">Sort: Suite order</option>
                    <option value="STATUS">Sort: Failing first</option>
                    <option value="ID">Sort: Case ID</option>
                  </select>
                </div>
              </div>

              {/* Scrollable Case List */}
              <div className="flex-1 space-y-1.5 overflow-y-auto p-2.5">
                {casesLoading && cases.length === 0 ? (
                  <div className="py-10 text-center text-xs text-bea-text-secondary">
                    Loading eval cases...
                  </div>
                ) : cases.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-bea-border bg-bea-card p-4 text-center text-xs text-bea-text-secondary">
                    No matching eval cases.
                  </div>
                ) : (
                  <>
                    {cases.map((c) => {
                      const isSelected = c.id === selectedCaseId;
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => setSelectedCaseId(c.id)}
                          className={`flex w-full cursor-pointer flex-col gap-1 rounded-xl border p-2.5 text-left transition ${
                            isSelected
                              ? "border-solar-red border-l-4 bg-bea-card shadow-xs"
                              : "border-bea-border bg-bea-card hover:border-solar-orange/60"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono text-xs font-extrabold text-solar-red">
                                {c.id}
                              </span>
                              <span className="text-[10px] font-medium text-bea-text-secondary">
                                {c.turn_count}t
                              </span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              {typeof c.score === "number" && (
                                <span className="font-mono text-[10px] font-semibold text-bea-text-secondary">
                                  {c.score}
                                </span>
                              )}
                              <StatusBadge status={c.status} />
                            </div>
                          </div>
                          <div className="line-clamp-2 text-xs font-medium text-bea-text-strong">
                            {c.first_question || "(No question)"}
                          </div>
                          {c.comment && (
                            <div className="line-clamp-1 text-[11px] text-bea-text-secondary">
                              {c.comment}
                            </div>
                          )}
                        </button>
                      );
                    })}

                    {casesHasMore && (
                      <button
                        type="button"
                        disabled={casesLoading}
                        onClick={() => void fetchCasesPage(cases.length, true)}
                        className="w-full cursor-pointer rounded-lg border border-bea-border bg-bea-card py-2 text-xs font-semibold text-bea-text-strong hover:bg-bea-canvas disabled:opacity-50"
                      >
                        {casesLoading
                          ? "Loading more..."
                          : `Load more (${cases.length} / ${casesTotal})`}
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </aside>

        {/* Right Case Detail Pane */}
        <main className="min-w-0 flex-1 overflow-y-auto bg-bea-canvas/45 p-5 pb-24">
          {!resolvedSuiteId || (!overview?.has_questions && !casesLoading && casesTotal === 0) ? (
            <div className="mx-auto mt-10 max-w-xl space-y-4 rounded-2xl border border-dashed border-bea-border bg-bea-card p-8 text-center shadow-xs">
              <div className="text-base font-bold text-bea-text-strong">
                {resolvedSuiteId
                  ? `Eval suite "${activeSuite?.name}" has no test cases yet`
                  : `No Eval Suites configured for ${projectName} (${activeEnv.toUpperCase()})`}
              </div>
              <p className="text-xs text-bea-text-secondary">
                All Eval Suites, Cases, Judge Rubrics, and Results are stored in SQLite DB (never polluting target repositories).
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                <button
                  type="button"
                  onClick={onOpenImportXlsx}
                  className="btn btn-sm btn-solar text-xs"
                >
                  <FileSpreadsheet className="h-3.5 w-3.5" />
                  Import .xlsx Workbook
                </button>
                <button
                  type="button"
                  onClick={onOpenCreateSuite}
                  className="btn btn-sm btn-secondary text-xs"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Create Empty Suite
                </button>
                <button
                  type="button"
                  disabled={importingLegacy}
                  onClick={handleImportLegacy}
                  className="btn btn-sm btn-secondary text-xs"
                >
                  <Database className="h-3.5 w-3.5 text-bea-teal" />
                  {importingLegacy
                    ? "Scanning..."
                    : "Scan Legacy scripts/uat/ (Read-Only)"}
                </button>
              </div>
              {legacyMessage && (
                <div className="rounded-lg border border-bea-border bg-bea-canvas p-2.5 text-xs text-bea-text-primary">
                  {legacyMessage}
                </div>
              )}
            </div>
          ) : detailLoading && !caseDetail ? (
            <div className="py-16 text-center text-xs text-bea-text-secondary">
              Loading case detail...
            </div>
          ) : detailError ? (
            <div className="rounded-xl border border-solar-red/40 bg-bea-coral/25 p-4 text-xs text-bea-burgundy">
              {detailError}
            </div>
          ) : !caseDetail ? (
            <div className="py-16 text-center text-xs text-bea-text-secondary">
              Select an eval case from the left sidebar to inspect turns, answers, retrieved sources, and judge checks.
            </div>
          ) : (
            <div className="mx-auto max-w-5xl space-y-4">
              {/* Case Summary Header Card */}
              <div className="rounded-2xl border border-bea-border bg-bea-card p-4 shadow-2xs">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-base font-extrabold text-solar-red">
                        {caseDetail.id}
                      </span>
                      <StatusBadge status={caseDetail.eval_review?.status} />
                      <span className="rounded-md border border-bea-border bg-bea-canvas px-2 py-0.5 font-mono text-[11px] font-bold text-bea-text-strong">
                        score={caseDetail.eval_review?.score ?? 0}
                      </span>
                      <span className="rounded-md border border-bea-border bg-bea-canvas px-2 py-0.5 text-[11px] font-semibold text-bea-text-secondary">
                        {caseDetail.turn_count}{" "}
                        {caseDetail.turn_count === 1 ? "turn" : "turns"}
                      </span>
                      <span className="rounded-md border border-bea-blue/30 bg-bea-blue/10 px-2 py-0.5 font-mono text-[11px] font-bold uppercase text-bea-blue">
                        {activeEnv}
                      </span>
                    </div>

                    {caseDetail.eval_review?.comment && (
                      <p className="text-xs leading-relaxed text-bea-text-primary">
                        <span className="font-bold text-bea-text-strong">
                          Eval Judge Summary:{" "}
                        </span>
                        {caseDetail.eval_review.comment}
                      </p>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    {overview?.has_config && (
                      <>
                        <button
                          type="button"
                          disabled={isEvalRunning}
                          onClick={() => {
                            setLogsModalOpen(true);
                            onStartRun({
                              suite_id: resolvedSuiteId,
                              case_ids: caseDetail.id,
                            });
                          }}
                          className="btn btn-sm btn-secondary text-xs"
                        >
                          <Play className="h-3 w-3 text-solar-red" />
                          Re-run {caseDetail.id}
                        </button>
                        <button
                          type="button"
                          disabled={isEvalRunning}
                          onClick={() => {
                            setLogsModalOpen(true);
                            onStartRun({
                              suite_id: resolvedSuiteId,
                              case_ids: caseDetail.id,
                              runs: 5,
                            });
                          }}
                          className="btn btn-sm btn-secondary text-xs"
                        >
                          <FlaskConical className="h-3 w-3 text-bea-teal" />
                          5x Stability
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        onDiagnoseCase(buildPromptForCase(caseDetail, false), false)
                      }
                      className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-bea-blue/35 bg-bea-blue/10 px-2.5 py-1.5 text-xs font-bold text-bea-blue transition hover:bg-bea-blue/20"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      Diagnose
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        onDiagnoseCase(buildPromptForCase(caseDetail, true), true)
                      }
                      className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-solar-red/35 bg-bea-coral/25 px-2.5 py-1.5 text-xs font-bold text-bea-burgundy transition hover:bg-bea-coral/40"
                    >
                      <Wrench className="h-3.5 w-3.5 text-solar-red" />
                      Fix with AGY
                    </button>
                  </div>
                </div>
              </div>

              {/* Per-Turn Cards */}
              {caseDetail.turns.map((turn) => {
                const turnReview = turn.eval_review || turn.uat_review;
                return (
                  <div
                    key={turn.turn}
                    className="space-y-3 rounded-2xl border border-bea-border bg-bea-card p-4 shadow-2xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-bea-border pb-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-extrabold text-bea-text-strong">
                          Turn {turn.turn}
                        </span>
                        <StatusBadge status={turnReview?.status} />
                      </div>
                      {overview?.has_config && (
                        <button
                          type="button"
                          disabled={isEvalRunning}
                          onClick={() => {
                            setLogsModalOpen(true);
                            onStartRun({
                              suite_id: resolvedSuiteId,
                              case_ids: caseDetail.id,
                              turn: turn.turn,
                            });
                          }}
                          title={`Replay conversation starting from Turn ${turn.turn}`}
                          className="btn btn-sm btn-secondary text-[11px]"
                        >
                          <RotateCcw className="h-3 w-3 text-bea-teal" />
                          Replay from Turn {turn.turn}
                        </button>
                      )}
                    </div>

                    <div>
                      <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-bea-text-secondary">
                        Question
                      </div>
                      <div className="rounded-xl border border-bea-border bg-bea-canvas/60 p-3 text-xs whitespace-pre-wrap text-bea-text-strong">
                        {turn.question}
                      </div>
                    </div>

                    {turn.raw_response?.error && (
                      <div className="rounded-xl border border-solar-red/40 bg-bea-coral/25 p-3 text-xs text-bea-burgundy">
                        Error: {turn.raw_response.error}
                      </div>
                    )}

                    {(turn.raw_response?.text || turn.expected_answer) && (
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        <div>
                          <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-bea-text-secondary">
                            Actual Answer
                          </div>
                          <div className="max-h-72 overflow-y-auto rounded-xl border border-bea-border bg-bea-canvas/55 p-3 text-xs">
                            {turn.raw_response?.text ? (
                              <MarkdownContent content={turn.raw_response.text} />
                            ) : (
                              <span className="italic text-bea-text-secondary">
                                Not evaluated yet
                              </span>
                            )}
                          </div>
                        </div>

                        <div>
                          <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-bea-text-secondary">
                            Expected Answer
                          </div>
                          <div className="max-h-72 overflow-y-auto rounded-xl border border-bea-border bg-bea-canvas/40 p-3 text-xs whitespace-pre-wrap text-bea-text-primary">
                            {turn.expected_answer || (
                              <span className="italic text-bea-text-secondary">
                                None specified
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {turn.raw_response?.sources &&
                      turn.raw_response.sources.length > 0 && (
                        <div>
                          <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-bea-text-secondary">
                            Retrieved Sources ({turn.raw_response.sources.length})
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {turn.raw_response.sources.map((src, i) => (
                              <span
                                key={i}
                                className="select-text rounded-md border border-bea-border bg-bea-canvas px-2 py-0.5 font-mono text-[11px] text-bea-teal"
                              >
                                {src}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                    {turn.expected_behavior && (
                      <div>
                        <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-bea-text-secondary">
                          Expected Behavior
                        </div>
                        <div className="rounded-xl border border-bea-border bg-bea-canvas/40 p-2.5 text-xs whitespace-pre-wrap text-bea-text-primary">
                          {turn.expected_behavior}
                        </div>
                      </div>
                    )}

                    {(turnReview?.behavior_check || turnReview?.answer_check) && (
                      <div className="space-y-1.5 rounded-xl border border-bea-border bg-bea-canvas/60 p-3 text-xs text-bea-text-primary">
                        {turnReview.behavior_check && (
                          <div>
                            <span className="font-bold text-bea-text-strong">
                              Behavior Check:{" "}
                            </span>
                            {turnReview.behavior_check}
                          </div>
                        )}
                        {turnReview.answer_check && (
                          <div>
                            <span className="font-bold text-bea-text-strong">
                              Answer Check:{" "}
                            </span>
                            {turnReview.answer_check}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </main>
      </div>

      {/* Eval Logs & Run History Modal */}
      {logsModalOpen && (
        <div
          onClick={() => setLogsModalOpen(false)}
          className="animate-view-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-bea-border bg-bea-card shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-bea-border px-5 py-3.5">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-bea-blue" />
                <h3 className="text-sm font-bold text-bea-text-strong">
                  Eval Logs &amp; Run History — {activeSuite?.name || projectName} (
                  {activeEnv.toUpperCase()})
                </h3>
                {isEvalRunning && (
                  <span className="rounded-full bg-solar-orange/20 px-2 py-0.5 text-[10px] font-bold text-solar-red-orange">
                    Live Stream
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setLogsModalOpen(false)}
                className="rounded-lg p-1 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-bea-border md:grid-cols-3 md:divide-x md:divide-y-0">
              {/* Recent Runs List */}
              <div className="space-y-1.5 overflow-y-auto bg-bea-surface-subtle p-3">
                <div className="px-1 text-[11px] font-bold uppercase text-bea-text-secondary">
                  Recent Runs ({overview?.runs?.length ?? 0})
                </div>
                {runningLogs.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setSelectedHistoricalRun(null)}
                    className={`w-full cursor-pointer rounded-lg border p-2 text-left text-xs ${
                      selectedHistoricalRun === null
                        ? "border-solar-red bg-bea-card font-bold"
                        : "border-bea-border bg-bea-card"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-solar-red">Current Session Stream</span>
                      {isEvalRunning && (
                        <span className="text-[10px] text-solar-orange">LIVE</span>
                      )}
                    </div>
                  </button>
                )}
                {(overview?.runs || []).map((r) => (
                  <button
                    key={r.job_id}
                    type="button"
                    onClick={() => void handleLoadHistoricalRun(r)}
                    className={`w-full cursor-pointer rounded-lg border p-2 text-left text-xs transition ${
                      selectedHistoricalRun?.run.job_id === r.job_id
                        ? "border-solar-red bg-bea-card"
                        : "border-bea-border bg-bea-card hover:border-solar-orange/60"
                    }`}
                  >
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="font-bold text-bea-text-strong">
                        {r.job_id}
                      </span>
                      <span
                        className={`font-bold uppercase ${
                          r.status === "completed"
                            ? "text-bea-teal"
                            : r.status === "running"
                            ? "text-solar-orange"
                            : "text-bea-burgundy"
                        }`}
                      >
                        {r.status}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between text-[10px] text-bea-text-secondary">
                      <span>{formatRelativeTime(r.started_at)}</span>
                      {typeof r.summary?.score_pct === "number" && (
                        <span>{r.summary.score_pct}%</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>

              {/* Log Output */}
              <div className="col-span-2 flex min-h-0 flex-col bg-neutral-950 p-3 font-mono text-[11px] leading-5 text-neutral-100">
                {loadingRunLogs ? (
                  <div className="py-8 text-center text-neutral-400">
                    Loading logs from SQLite DB...
                  </div>
                ) : selectedHistoricalRun ? (
                  <div className="flex-1 overflow-auto">
                    {selectedHistoricalRun.lines.length > 0 ? (
                      selectedHistoricalRun.lines.map((ln, idx) => (
                        <div key={idx} className="whitespace-pre-wrap">
                          {ln}
                        </div>
                      ))
                    ) : (
                      <div className="text-neutral-400">
                        No logs recorded for {selectedHistoricalRun.run.job_id}.
                      </div>
                    )}
                  </div>
                ) : runningLogs.length > 0 ? (
                  <div className="flex-1 overflow-auto">
                    {runningLogs.map((ln, idx) => (
                      <div key={idx} className="whitespace-pre-wrap">
                        {ln}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-8 text-center text-neutral-400">
                    No active eval logs yet. Select a past run on the left or start an Eval Run.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
