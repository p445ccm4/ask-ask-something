"use client";

import React, { useState } from "react";
import {
  FolderPlus,
  GitBranch,
  Rocket,
  ShieldCheck,
} from "lucide-react";
import type { TargetEnv, WorkspaceSummary } from "@/lib/types";

interface HeaderBarProps {
  workspaces: WorkspaceSummary[];
  activeWorkspaceId: string;
  onSelectWorkspace: (wsId: string) => void;
  onAddWorkspace: (payload: {
    name: string;
    path: string;
    uat_path?: string;
  }) => Promise<void>;
  onOpenGitDiff: () => void;
  onOpenDeploy: (env: TargetEnv) => void;
}

export function HeaderBar({
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
  onAddWorkspace,
  onOpenGitDiff,
  onOpenDeploy,
}: HeaderBarProps) {
  const [showAddRepo, setShowAddRepo] = useState(false);
  const [repoName, setRepoName] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [uatPath, setUatPath] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId) || null;

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAdding(true);
    setAddError(null);
    try {
      await onAddWorkspace({
        name: repoName.trim(),
        path: repoPath.trim(),
        uat_path: uatPath.trim() || undefined,
      });
      setShowAddRepo(false);
      setRepoName("");
      setRepoPath("");
      setUatPath("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : String(err));
    } finally {
      setAdding(false);
    }
  };

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-bea-border bg-bea-card px-4 py-2.5 shadow-xs">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2.5">
            <div className="white-on-solar flex h-8 w-8 items-center justify-center rounded-lg shadow-sm">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <div className="solar-on-white text-sm font-extrabold tracking-tight">
                AskAsk* Workbench
              </div>
              <div className="text-[10px] font-medium text-bea-text-secondary">
                UAT Runner + Antigravity SDK
              </div>
            </div>
          </div>

          <div className="h-5 w-px bg-bea-border" />

          <div className="flex items-center gap-1.5">
            <select
              value={activeWorkspaceId}
              onChange={(e) => onSelectWorkspace(e.target.value)}
              aria-label="Target repository workspace"
              className="cursor-pointer rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs font-semibold text-bea-text-strong focus:border-solar-red focus:outline-none"
            >
              {workspaces.map((ws) => (
                <option key={ws.id} value={ws.id}>
                  {ws.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setShowAddRepo(true)}
              title="Add another local agent repo"
              className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2 py-1.5 text-xs text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas hover:text-bea-text-strong"
            >
              <FolderPlus className="h-3.5 w-3.5" />
            </button>
          </div>

          {activeWs && (
            <button
              type="button"
              onClick={onOpenGitDiff}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas hover:text-bea-text-strong"
            >
              <GitBranch className="h-3.5 w-3.5 text-solar-red" />
              <span className="font-mono font-medium">{activeWs.branch || "no-git"}</span>
              {(activeWs.dirty_count > 0 || activeWs.unpushed_count > 0) && (
                <span className="font-mono text-[11px] font-bold text-bea-burgundy">
                  · {activeWs.dirty_count}M
                  {activeWs.unpushed_count > 0 ? ` ${activeWs.unpushed_count}↑` : ""}
                </span>
              )}
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* Human-Only Deploy Push Controls */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={!activeWs}
              onClick={() => onOpenDeploy("dev")}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-bea-teal-solid px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Rocket className="h-3.5 w-3.5" />
              Deploy to DEV
            </button>
            <button
              type="button"
              disabled={!activeWs || (!activeWs.uat_exists && activeWs.env !== "uat")}
              onClick={() => onOpenDeploy("uat")}
              title={
                activeWs && !activeWs.uat_exists && activeWs.env !== "uat"
                  ? "No paired UAT repo configured for this workspace"
                  : "Preview & push changes to UAT main branch"
              }
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-bea-emerald px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Rocket className="h-3.5 w-3.5" />
              Deploy to UAT
            </button>
          </div>
        </div>
      </header>

      {showAddRepo && (
        <div className="animate-view-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]">
          <form
            onSubmit={handleAddSubmit}
            className="w-full max-w-lg space-y-4 rounded-2xl border border-bea-border bg-bea-card p-6 shadow-2xl"
          >
            <h3 className="text-base font-bold text-bea-text-strong">Add Agent Repository</h3>
            {addError && (
              <div className="rounded-lg border border-solar-red/40 bg-bea-coral/25 p-2.5 text-xs text-bea-burgundy">
                {addError}
              </div>
            )}
            <div>
              <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                Display Name
              </label>
              <input
                type="text"
                required
                value={repoName}
                onChange={(e) => setRepoName(e.target.value)}
                placeholder="e.g. Sample Agent (DEV)"
                className="w-full rounded-lg border border-bea-border bg-bea-card px-3 py-2 text-sm text-bea-text-strong focus:border-solar-red focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                Local DEV Repository / Service Path
              </label>
              <input
                type="text"
                required
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="/path/to/dev-repo/sample-agent-service"
                className="w-full rounded-lg border border-bea-border bg-bea-card px-3 py-2 font-mono text-xs text-bea-text-strong focus:border-solar-red focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                Optional Paired UAT Path (for Deploy to UAT promotion)
              </label>
              <input
                type="text"
                value={uatPath}
                onChange={(e) => setUatPath(e.target.value)}
                placeholder="/path/to/uat-repo/sample-agent-service"
                className="w-full rounded-lg border border-bea-border bg-bea-card px-3 py-2 font-mono text-xs text-bea-text-strong focus:border-solar-red focus:outline-none"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAddRepo(false)}
                className="rounded-lg border border-bea-border px-3.5 py-2 text-xs font-medium text-bea-text-primary hover:bg-bea-canvas"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={adding}
                className="white-on-solar rounded-lg px-4 py-2 text-xs font-semibold shadow-sm transition hover:opacity-95 disabled:opacity-50"
              >
                {adding ? "Adding..." : "Add Repository"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
