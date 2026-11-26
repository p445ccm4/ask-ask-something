"use client";

import React, { useState } from "react";
import {
  FolderPlus,
  GitBranch,
  Rocket,
  ShieldCheck,
} from "lucide-react";
import type { TargetEnv, WorkspaceSummary } from "@/lib/types";
import { AddRepoModal } from "./AddRepoModal";

interface HeaderBarProps {
  workspaces: WorkspaceSummary[];
  activeWorkspaceId: string;
  onSelectWorkspace: (wsId: string) => void;
  onAddWorkspace: (payload: {
    name: string;
    path: string;
    uat_path?: string;
  }) => Promise<void>;
  onOpenGitDiff: (repo?: TargetEnv) => void;
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

  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId) || null;
  const uatDirtyCount = activeWs?.uat_dirty_count ?? 0;
  const uatUnpushedCount = activeWs?.uat_unpushed_count ?? 0;

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
              className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 text-xs font-semibold text-bea-text-strong shadow-2xs transition hover:border-solar-red hover:bg-bea-canvas"
            >
              <FolderPlus className="h-3.5 w-3.5 text-solar-red-orange" />
              <span className="hidden sm:inline">Add Repo</span>
            </button>
          </div>

          {activeWs && (
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => onOpenGitDiff("dev")}
                title="Inspect DEV git diff"
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
              {activeWs.uat_exists && (uatDirtyCount > 0 || uatUnpushedCount > 0) && (
                <button
                  type="button"
                  onClick={() => onOpenGitDiff("uat")}
                  title={`Inspect paired UAT git diff (${activeWs.uat_branch || "main"})`}
                  className="inline-flex cursor-pointer items-center gap-1 rounded-lg border border-bea-emerald/45 bg-bea-emerald/10 px-2 py-1.5 font-mono text-[11px] font-bold text-bea-teal shadow-2xs transition hover:bg-bea-emerald/20"
                >
                  <span>UAT:</span>
                  <span>
                    {uatDirtyCount}M{uatUnpushedCount > 0 ? ` ${uatUnpushedCount}↑` : ""}
                  </span>
                </button>
              )}
            </div>
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

      <AddRepoModal
        open={showAddRepo}
        onClose={() => setShowAddRepo(false)}
        onAddWorkspace={onAddWorkspace}
      />
    </>
  );
}
