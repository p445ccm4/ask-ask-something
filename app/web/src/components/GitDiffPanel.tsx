"use client";

import React from "react";
import { GitBranch, RefreshCw, Rocket, X } from "lucide-react";
import type { TargetEnv, WorkspaceGitInfo } from "@/lib/types";
import { DiffViewer } from "./DiffViewer";

interface GitDiffPanelProps {
  open: boolean;
  onClose: () => void;
  workspaceName: string;
  hasUatTarget: boolean;
  hasPairedUat: boolean;
  activeRepo: TargetEnv;
  onChangeRepo: (repo: TargetEnv) => void;
  gitInfo: WorkspaceGitInfo | null;
  uatGitInfo: WorkspaceGitInfo | null;
  loading: boolean;
  onRefresh: () => void;
  onOpenDeploy: (env: TargetEnv) => void;
}

export function GitDiffPanel({
  open,
  onClose,
  workspaceName,
  hasUatTarget,
  hasPairedUat,
  activeRepo,
  onChangeRepo,
  gitInfo,
  uatGitInfo,
  loading,
  onRefresh,
  onOpenDeploy,
}: GitDiffPanelProps) {
  if (!open) return null;

  const shownRepo: TargetEnv = hasPairedUat && activeRepo === "uat" ? "uat" : "dev";
  const shownGit = shownRepo === "uat" ? uatGitInfo : gitInfo;
  const devDirtyCount = gitInfo?.changed_files.length ?? 0;
  const uatDirtyCount = uatGitInfo?.changed_files.length ?? 0;

  return (
    <div className="animate-view-fade-in fixed inset-0 z-40 flex justify-end bg-black/40 backdrop-blur-[2px]">
      <div className="flex h-full w-full max-w-3xl flex-col border-l border-bea-border bg-bea-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-bea-border px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <GitBranch className="h-4 w-4 text-solar-red" />
              <h2 className="text-sm font-bold text-bea-text-strong">
                Service Git Diff — {workspaceName}
                {hasPairedUat ? ` (${shownRepo.toUpperCase()})` : ""}
              </h2>
            </div>
            <p className="mt-0.5 text-xs text-bea-text-secondary">
              Scoped strictly to <code className="text-bea-text-strong">{shownGit?.service_subpath || "."}</code> on branch{" "}
              <code className="font-semibold text-bea-teal">{shownGit?.branch || "unknown"}</code>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs font-medium text-bea-text-primary hover:bg-bea-canvas disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
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

        {hasPairedUat && (
          <div className="flex items-center gap-2 border-b border-bea-border bg-bea-canvas/50 px-5 py-2">
            <button
              type="button"
              onClick={() => onChangeRepo("dev")}
              className={`cursor-pointer rounded-lg border px-3 py-1 text-xs font-semibold transition ${
                shownRepo === "dev"
                  ? "border-bea-teal bg-bea-teal-solid text-white shadow-2xs"
                  : "border-bea-border bg-bea-card text-bea-text-secondary hover:text-bea-text-strong"
              }`}
            >
              DEV Repo{devDirtyCount > 0 ? ` (${devDirtyCount})` : ""}
            </button>
            <button
              type="button"
              onClick={() => onChangeRepo("uat")}
              className={`cursor-pointer rounded-lg border px-3 py-1 text-xs font-semibold transition ${
                shownRepo === "uat"
                  ? "border-bea-emerald bg-bea-emerald text-white shadow-2xs"
                  : "border-bea-border bg-bea-card text-bea-text-secondary hover:text-bea-text-strong"
              }`}
            >
              Paired UAT Repo{uatDirtyCount > 0 ? ` (${uatDirtyCount})` : ""}
            </button>
          </div>
        )}

        <div className="flex-1 space-y-4 overflow-y-auto bg-bea-canvas/40 p-5">
          {shownGit?.remote_url && (
            <div className="rounded-xl border border-bea-border bg-bea-card px-3.5 py-2.5 text-xs text-bea-text-primary">
              <span className="text-bea-text-secondary">Origin remote: </span>
              <code className="font-mono text-bea-blue">{shownGit.remote_url}</code>
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
                    <span className="truncate font-mono text-bea-text-strong">{f.path}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-bea-text-secondary">
                Working tree clean for this {shownRepo.toUpperCase()} service.
              </p>
            )}
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-bea-text-secondary">
              Unified Diff
            </h3>
            <DiffViewer diff={shownGit?.diff || ""} maxHeightClass="max-h-[55vh]" />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-bea-border bg-bea-card px-5 py-3.5">
          <span className="text-xs text-bea-text-secondary">
            AI agents cannot run <code>git push</code> — use these human-only deploy actions:
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenDeploy("dev");
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-bea-teal-solid px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90"
            >
              <Rocket className="h-3.5 w-3.5" />
              Deploy to DEV
            </button>
            {hasUatTarget && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenDeploy("uat");
                }}
                className="inline-flex items-center gap-1.5 rounded-lg bg-bea-emerald px-3 py-1.5 text-xs font-semibold text-white transition hover:opacity-90"
              >
                <Rocket className="h-3.5 w-3.5" />
                Deploy to UAT
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
