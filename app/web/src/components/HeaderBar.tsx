"use client";

import React, { useState } from "react";
import {
  Eye,
  FolderPlus,
  GitBranch,
  Rocket,
  Shield,
  ShieldCheck,
  Zap,
} from "lucide-react";
import type {
  ExecutionMode,
  HealthStatus,
  TargetEnv,
  WorkspaceSummary,
} from "@/lib/types";

interface HeaderBarProps {
  workspaces: WorkspaceSummary[];
  activeWorkspaceId: string;
  onSelectWorkspace: (wsId: string) => void;
  onAddWorkspace: (payload: {
    name: string;
    path: string;
    uat_path?: string;
  }) => Promise<void>;
  mode: ExecutionMode;
  onChangeMode: (mode: ExecutionMode) => void;
  health: HealthStatus | null;
  onOpenGitDiff: () => void;
  onOpenDeploy: (env: TargetEnv) => void;
}

export function HeaderBar({
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
  onAddWorkspace,
  mode,
  onChangeMode,
  health,
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
              className="cursor-pointer rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs font-semibold text-neutral-800 focus:border-solar-red focus:outline-none"
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
              className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-border bg-bea-card px-2 py-1.5 text-xs text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas hover:text-neutral-900"
            >
              <FolderPlus className="h-3.5 w-3.5" />
            </button>
          </div>

          {activeWs && (
            <button
              type="button"
              onClick={onOpenGitDiff}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs text-bea-text-primary shadow-2xs transition hover:bg-bea-canvas hover:text-neutral-900"
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

          {health?.sandbox_status && (
            <span
              className="hidden select-none items-center gap-1.5 rounded bg-bea-canvas px-2 py-1 text-[11px] font-medium text-bea-text-secondary xl:inline-flex"
              title={
                health.sandbox_status.unavailable_reason ||
                "Linux kernel user-namespace sandbox is active"
              }
            >
              <Shield
                className={`h-3 w-3 ${
                  health.sandbox_status.available ? "text-bea-emerald" : "text-solar-orange"
                }`}
              />
              {health.sandbox_status.available ? "Sandbox Ready" : "Sandbox Unavailable"}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {/* 3-Way Execution Mode Toggle */}
          <div
            className="inline-flex rounded-xl border border-bea-border bg-bea-canvas p-0.5"
            role="group"
            aria-label="Antigravity execution mode"
          >
            <button
              type="button"
              onClick={() => onChangeMode("read_only")}
              className={`inline-flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                mode === "read_only"
                  ? "bg-bea-card text-bea-blue shadow-xs ring-1 ring-bea-border"
                  : "text-bea-text-secondary hover:text-neutral-800"
              }`}
            >
              <Eye className="h-3.5 w-3.5" />
              Read-Only
            </button>
            <button
              type="button"
              onClick={() => onChangeMode("ask_before_fix")}
              className={`inline-flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                mode === "ask_before_fix"
                  ? "bg-bea-card text-solar-red-orange shadow-xs ring-1 ring-solar-orange/40"
                  : "text-bea-text-secondary hover:text-neutral-800"
              }`}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Ask-Before-Fix
            </button>
            <button
              type="button"
              onClick={() => onChangeMode("sandboxed_auto")}
              className={`inline-flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                mode === "sandboxed_auto"
                  ? "bg-bea-card text-bea-teal shadow-xs ring-1 ring-bea-emerald/40"
                  : "text-bea-text-secondary hover:text-neutral-800"
              }`}
            >
              <Zap className="h-3.5 w-3.5" />
              Sandboxed Auto
            </button>
          </div>

          <div className="h-5 w-px bg-bea-border" />

          {/* Human-Only Deploy Push Controls */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={!activeWs}
              onClick={() => onOpenDeploy("dev")}
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-bea-teal px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
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
            <h3 className="text-base font-bold text-neutral-800">Add Agent Repository</h3>
            {addError && (
              <div className="rounded-lg border border-solar-red/40 bg-bea-coral/25 p-2.5 text-xs text-bea-burgundy">
                {addError}
              </div>
            )}
            <div>
              <label className="mb-1 block text-xs font-semibold text-neutral-700">
                Display Name
              </label>
              <input
                type="text"
                required
                value={repoName}
                onChange={(e) => setRepoName(e.target.value)}
                placeholder="e.g. Sample Agent (DEV)"
                className="w-full rounded-lg border border-bea-border bg-bea-card px-3 py-2 text-sm text-neutral-800 focus:border-solar-red focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-neutral-700">
                Local DEV Repository / Service Path
              </label>
              <input
                type="text"
                required
                value={repoPath}
                onChange={(e) => setRepoPath(e.target.value)}
                placeholder="/path/to/dev-repo/sample-agent-service"
                className="w-full rounded-lg border border-bea-border bg-bea-card px-3 py-2 font-mono text-xs text-neutral-800 focus:border-solar-red focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-neutral-700">
                Optional Paired UAT Path (for Deploy to UAT promotion)
              </label>
              <input
                type="text"
                value={uatPath}
                onChange={(e) => setUatPath(e.target.value)}
                placeholder="/path/to/uat-repo/sample-agent-service"
                className="w-full rounded-lg border border-bea-border bg-bea-card px-3 py-2 font-mono text-xs text-neutral-800 focus:border-solar-red focus:outline-none"
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
