"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeftRight,
  CheckCircle2,
  GitBranch,
  Lock,
  RefreshCw,
  Rocket,
  X,
} from "lucide-react";
import { apiUrl } from "@/lib/basePath";
import {
  ENV_ORDER,
  type CompareEnvsResult,
  type EnvName,
  type ProjectSummary,
  type TargetEnv,
  type WorkspaceGitInfo,
} from "@/lib/types";
import { DiffViewer } from "./DiffViewer";

interface GitDiffPanelProps {
  open: boolean;
  onClose: () => void;
  project: ProjectSummary | null;
  activeEnv: EnvName;
  onChangeEnv: (env: EnvName) => void;
  gitInfoByEnv: Partial<Record<EnvName, WorkspaceGitInfo>>;
  loading: boolean;
  onRefresh: () => void;
  onOpenDeploy: (env: TargetEnv) => void;
}

export function GitDiffPanel({
  open,
  onClose,
  project,
  activeEnv,
  onChangeEnv,
  gitInfoByEnv,
  loading,
  onRefresh,
  onOpenDeploy,
}: GitDiffPanelProps) {
  const configuredEnvs = useMemo(
    () => project?.configured_envs ?? [],
    [project?.configured_envs]
  );
  const [tabMode, setTabMode] = useState<"env" | "compare">("env");
  const [sourceEnv, setSourceEnv] = useState<EnvName>("dev");
  const [targetEnv, setTargetEnv] = useState<EnvName>("uat");
  const [includeConfigPy, setIncludeConfigPy] = useState(false);
  const [compareData, setCompareData] = useState<CompareEnvsResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || configuredEnvs.length < 2) return;
    if (!configuredEnvs.includes(targetEnv)) {
      setTargetEnv(configuredEnvs[configuredEnvs.length - 1]);
    }
    if (!configuredEnvs.includes(sourceEnv) || sourceEnv === targetEnv) {
      const other = configuredEnvs.find((e) => e !== targetEnv);
      if (other) setSourceEnv(other);
    }
  }, [open, configuredEnvs, sourceEnv, targetEnv]);

  const loadComparison = useCallback(async () => {
    if (!project || configuredEnvs.length < 2 || sourceEnv === targetEnv) return;
    setCompareLoading(true);
    setCompareError(null);
    try {
      const res = await fetch(
        apiUrl(
          `/api/projects/${encodeURIComponent(
            project.id
          )}/compare?source_env=${sourceEnv}&target_env=${targetEnv}&include_config_py=${includeConfigPy}`
        )
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to compare environments");
      }
      setCompareData(data as CompareEnvsResult);
    } catch (err) {
      setCompareError(err instanceof Error ? err.message : String(err));
    } finally {
      setCompareLoading(false);
    }
  }, [project, configuredEnvs.length, sourceEnv, targetEnv, includeConfigPy]);

  useEffect(() => {
    if (open && tabMode === "compare") {
      void loadComparison();
    }
  }, [open, tabMode, loadComparison]);

  if (!open || !project) return null;

  const shownEnv: EnvName = configuredEnvs.includes(activeEnv)
    ? activeEnv
    : configuredEnvs[0] || "dev";
  const shownGit = gitInfoByEnv[shownEnv] || null;

  return (
    <div className="animate-view-fade-in fixed inset-0 z-40 flex justify-end bg-black/40 backdrop-blur-[2px]">
      <div className="flex h-full w-full max-w-4xl flex-col border-l border-bea-border bg-bea-card shadow-2xl">
        {/* Drawer Header */}
        <div className="flex items-center justify-between border-b border-bea-border px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-solar-red" />
              <h2 className="text-sm font-bold text-bea-text-strong">
                Git Diff &amp; Environment Compare — {project.name}
                {tabMode === "env" ? ` (${shownEnv.toUpperCase()})` : ""}
              </h2>
            </div>
            <p className="mt-0.5 text-xs text-bea-text-secondary">
              {tabMode === "env" ? (
                <>
                  Scoped strictly to{" "}
                  <code className="text-bea-text-strong">
                    {shownGit?.service_subpath || "."}
                  </code>{" "}
                  on branch{" "}
                  <code className="font-semibold text-bea-teal">
                    {shownGit?.branch || "unknown"}
                  </code>
                </>
              ) : (
                <>
                  Compare code &amp; config between configured environments (
                  {sourceEnv.toUpperCase()} → {targetEnv.toUpperCase()})
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={tabMode === "compare" ? loadComparison : onRefresh}
              disabled={loading || compareLoading}
              className="btn btn-sm btn-secondary text-xs"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${
                  loading || compareLoading ? "animate-spin" : ""
                }`}
              />
              Refresh
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Env Tabs + Compare Envs Tab */}
        <div className="flex flex-wrap items-center gap-1.5 border-b border-bea-border bg-bea-canvas/60 px-5 py-2.5">
          {ENV_ORDER.filter((e) => configuredEnvs.includes(e)).map((env) => {
            const dirty =
              gitInfoByEnv[env]?.changed_files.length ??
              project.env_git?.[env]?.dirty_count ??
              0;
            const isSelected = tabMode === "env" && shownEnv === env;
            return (
              <button
                key={env}
                type="button"
                onClick={() => {
                  setTabMode("env");
                  onChangeEnv(env);
                }}
                className={`cursor-pointer rounded-lg border px-3 py-1 text-xs font-bold uppercase transition ${
                  isSelected
                    ? "border-solar-red bg-solar-red text-white shadow-2xs"
                    : "border-bea-border bg-bea-card text-bea-text-secondary hover:text-bea-text-strong"
                }`}
              >
                {env}
                {dirty > 0 ? ` (${dirty})` : ""}
              </button>
            );
          })}

          {configuredEnvs.length >= 2 && (
            <button
              type="button"
              onClick={() => setTabMode("compare")}
              className={`ml-auto inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1 text-xs font-bold transition ${
                tabMode === "compare"
                  ? "border-bea-teal bg-bea-teal-solid text-white shadow-2xs"
                  : "border-bea-border bg-bea-card text-bea-text-strong hover:bg-bea-canvas"
              }`}
            >
              <ArrowLeftRight className="h-3.5 w-3.5" />
              Compare Envs
            </button>
          )}
        </div>

        {/* Drawer Content */}
        <div className="flex-1 space-y-4 overflow-y-auto bg-bea-canvas/40 p-5">
          {tabMode === "env" ? (
            <>
              {shownGit?.remote_url && (
                <div className="rounded-xl border border-bea-border bg-bea-card px-3.5 py-2.5 text-xs text-bea-text-primary">
                  <span className="text-bea-text-secondary">Origin remote: </span>
                  <code className="font-mono text-bea-blue">
                    {shownGit.remote_url}
                  </code>
                </div>
              )}

              {shownGit && shownGit.unpushed_commits.length > 0 && (
                <div className="rounded-xl border border-solar-orange/40 bg-solar-yellow/10 p-3.5">
                  <div className="text-xs font-semibold text-bea-burgundy">
                    Unpushed Local Commits ({shownGit.unpushed_commits.length})
                  </div>
                  <ul className="mt-1.5 space-y-1 font-mono text-[11px] text-bea-text-primary">
                    {shownGit.unpushed_commits.map((c, idx) => (
                      <li key={idx}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-bea-text-secondary">
                  Modified Service Files ({shownGit?.changed_files.length ?? 0})
                </h3>
                {shownGit && shownGit.changed_files.length > 0 ? (
                  <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                    {shownGit.changed_files.map((f) => (
                      <div
                        key={f.path}
                        className="flex items-center gap-2 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs"
                      >
                        <span className="rounded bg-solar-orange/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-solar-red-orange">
                          {f.status}
                        </span>
                        <span className="truncate font-mono text-bea-text-strong">
                          {f.path}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-bea-text-secondary">
                    Working tree clean for {shownEnv.toUpperCase()}.
                  </p>
                )}
              </div>

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-bea-text-secondary">
                  Unified Diff
                </h3>
                <DiffViewer
                  diff={shownGit?.diff || ""}
                  maxHeightClass="max-h-[55vh]"
                />
              </div>
            </>
          ) : (
            <>
              {/* Compare Envs Controls */}
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bea-border bg-bea-card p-3.5 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-bea-text-secondary">
                    Source:
                  </span>
                  <select
                    value={sourceEnv}
                    onChange={(e) => setSourceEnv(e.target.value as EnvName)}
                    className="rounded-lg border border-bea-border bg-bea-canvas px-2.5 py-1 font-bold uppercase text-bea-text-strong"
                  >
                    {configuredEnvs.map((e) => (
                      <option key={e} value={e} disabled={e === targetEnv}>
                        {e.toUpperCase()}
                      </option>
                    ))}
                  </select>
                  <span className="font-bold text-bea-text-secondary">→</span>
                  <span className="font-semibold text-bea-text-secondary">
                    Target:
                  </span>
                  <select
                    value={targetEnv}
                    onChange={(e) => setTargetEnv(e.target.value as EnvName)}
                    className="rounded-lg border border-bea-border bg-bea-canvas px-2.5 py-1 font-bold uppercase text-bea-text-strong"
                  >
                    {configuredEnvs.map((e) => (
                      <option key={e} value={e} disabled={e === sourceEnv}>
                        {e.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </div>

                <label className="flex cursor-pointer items-center gap-1.5 font-medium text-bea-text-primary">
                  <input
                    type="checkbox"
                    checked={includeConfigPy}
                    onChange={(e) => setIncludeConfigPy(e.target.checked)}
                    className="checkbox"
                  />
                  Include <code>src/config.py</code>
                </label>
              </div>

              {compareError && (
                <div className="rounded-xl border border-solar-red/40 bg-bea-coral/25 p-3 text-xs text-bea-burgundy">
                  {compareError}
                </div>
              )}

              {compareLoading ? (
                <div className="py-12 text-center text-xs text-bea-text-secondary">
                  Comparing {sourceEnv.toUpperCase()} and{" "}
                  {targetEnv.toUpperCase()}...
                </div>
              ) : compareData ? (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-bea-border bg-bea-card px-4 py-3 text-xs">
                    <div className="flex items-center gap-2">
                      {compareData.in_sync ? (
                        <span className="tag tag-success">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          In Sync
                        </span>
                      ) : (
                        <span className="tag tag-warning">
                          {compareData.changed_files.length} differing ·{" "}
                          {compareData.target_only_files.length} target-only
                        </span>
                      )}
                      <span className="text-bea-text-secondary">
                        Branches:{" "}
                        <code className="text-bea-text-strong">
                          {compareData.source_branch || "?"}
                        </code>{" "}
                        →{" "}
                        <code className="text-bea-text-strong">
                          {compareData.target_branch || "?"}
                        </code>
                      </span>
                    </div>
                    {compareData.protected_files.length > 0 && (
                      <span className="inline-flex items-center gap-1 text-bea-teal">
                        <Lock className="h-3.5 w-3.5" />
                        <code>src/config.py</code> excluded
                      </span>
                    )}
                  </div>

                  {(compareData.changed_files.length > 0 ||
                    compareData.target_only_files.length > 0) && (
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                      {compareData.changed_files.map((f) => (
                        <div
                          key={f.path}
                          className="flex items-center gap-2 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs"
                        >
                          <span className="rounded bg-solar-orange/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-solar-red-orange">
                            {f.status}
                          </span>
                          <span className="truncate font-mono text-bea-text-strong">
                            {f.path}
                          </span>
                        </div>
                      ))}
                      {compareData.target_only_files.map((p) => (
                        <div
                          key={p}
                          className="flex items-center gap-2 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs"
                        >
                          <span className="rounded bg-bea-coral/25 px-1.5 py-0.5 font-mono text-[10px] font-bold text-bea-burgundy">
                            TARGET-ONLY
                          </span>
                          <span className="truncate font-mono text-bea-text-strong">
                            {p}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  <DiffViewer
                    diff={compareData.diff}
                    emptyMessage={`${sourceEnv.toUpperCase()} and ${targetEnv.toUpperCase()} are identical.`}
                    maxHeightClass="max-h-[52vh]"
                  />
                </>
              ) : null}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-bea-border bg-bea-card px-5 py-3.5">
          <span className="text-xs text-bea-text-secondary">
            AI agents cannot run <code>git push</code> — use human-only deploy actions:
          </span>
          <div className="flex flex-wrap items-center gap-2">
            {ENV_ORDER.filter((e) => configuredEnvs.includes(e)).map((env) => (
              <button
                key={env}
                type="button"
                onClick={() => {
                  onClose();
                  onOpenDeploy(env);
                }}
                className="btn btn-sm btn-secondary font-bold uppercase"
              >
                <Rocket className="h-3.5 w-3.5 text-solar-red" />
                Deploy {env}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
