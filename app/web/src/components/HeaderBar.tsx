"use client";

import React from "react";
import {
  FolderCog,
  FolderPlus,
  GitBranch,
  Rocket,
  Sparkles,
} from "lucide-react";
import {
  ENV_LABELS,
  ENV_ORDER,
  type EnvName,
  type ProjectSummary,
  type TargetEnv,
} from "@/lib/types";

interface HeaderBarProps {
  projects: ProjectSummary[];
  activeProjectId: string;
  activeEnv: EnvName;
  activeEndpoint?: string | null;
  onSelectProject: (projectId: string) => void;
  onSelectEnv: (env: EnvName) => void;
  onOpenNewProject: () => void;
  onOpenEditProject: () => void;
  onOpenGitDiff: (env?: TargetEnv) => void;
  onOpenDeploy: (env: TargetEnv) => void;
}

const ACTIVE_ENV_CLASSES: Record<EnvName, string> = {
  sbx: "bg-bea-text-strong text-bea-card shadow-xs",
  dev: "bg-bea-blue text-white shadow-xs",
  uat: "bg-solar-orange text-white shadow-xs",
  prod: "bg-bea-emerald text-white shadow-xs",
};

export function HeaderBar({
  projects,
  activeProjectId,
  activeEnv,
  activeEndpoint,
  onSelectProject,
  onSelectEnv,
  onOpenNewProject,
  onOpenEditProject,
  onOpenGitDiff,
  onOpenDeploy,
}: HeaderBarProps) {
  const activeProject =
    projects.find((p) => p.id === activeProjectId) || null;
  const activeGit = activeProject?.env_git?.[activeEnv];
  const activePath =
    activeProject?.environments?.[activeEnv] || activeProject?.path || "";
  const activeBranch = activeGit?.branch ?? activeProject?.branch ?? null;
  const dirtyCount = activeGit?.dirty_count ?? activeProject?.dirty_count ?? 0;
  const unpushedCount =
    activeGit?.unpushed_count ?? activeProject?.unpushed_count ?? 0;
  const evalEndpoint =
    activeEndpoint?.trim() ||
    activeProject?.env_eval?.[activeEnv]?.endpoint ||
    "";

  return (
    <header className="flex flex-col gap-2 border-b border-bea-border bg-bea-card px-4 py-2.5 shadow-xs">
      {/* Row 1: Brand + Project + Env Switcher + Repo Config + Git/Deploy */}
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Brand lockup */}
          <div className="flex items-center gap-2.5">
            <div className="white-on-solar flex h-8 w-8 items-center justify-center rounded-lg text-xs font-extrabold tracking-tight shadow-sm">
              A<Sparkles className="ml-0.5 h-3 w-3 text-solar-yellow" />
            </div>
            <div>
              <div className="solar-on-white text-sm font-extrabold tracking-tight">
                AskAsk* Workbench
              </div>
              <div className="text-[11px] font-medium text-bea-text-secondary">
                Multi-Env Eval &amp; Maintainer
              </div>
            </div>
          </div>

          <div className="hidden h-5 w-px bg-bea-border sm:block" />

          {/* Project Selector */}
          <select
            value={activeProjectId}
            onChange={(e) => onSelectProject(e.target.value)}
            aria-label="Active Project"
            className="cursor-pointer rounded-lg border border-bea-border bg-bea-canvas px-2.5 py-1.5 text-xs font-bold text-bea-text-strong focus:border-solar-red focus:outline-none"
          >
            {projects.length === 0 ? (
              <option value="">No projects yet</option>
            ) : (
              projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))
            )}
          </select>

          {/* Multi-Env Pill Switcher (SBX | DEV | UAT | PROD) */}
          <div
            className="inline-flex items-center gap-0.5 rounded-lg border border-bea-border bg-bea-canvas p-0.5"
            role="tablist"
            aria-label="Environment"
          >
            {ENV_ORDER.map((env) => {
              const configured = Boolean(
                activeProject?.configured_envs?.includes(env)
              );
              const isActive = activeEnv === env;
              const envDirty = activeProject?.env_git?.[env]?.dirty_count ?? 0;
              return (
                <button
                  key={env}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  disabled={!activeProject || !configured}
                  onClick={() => onSelectEnv(env)}
                  title={
                    configured
                      ? `Switch to ${ENV_LABELS[env]} (${env.toUpperCase()})`
                      : `${env.toUpperCase()} repo not configured — click Project Paths`
                  }
                  className={`inline-flex cursor-pointer items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-bold uppercase transition ${
                    isActive
                      ? ACTIVE_ENV_CLASSES[env]
                      : configured
                      ? "text-bea-text-secondary hover:bg-bea-card hover:text-bea-text-strong"
                      : "cursor-not-allowed text-bea-text-secondary/40 line-through"
                  }`}
                >
                  <span>{env}</span>
                  {configured && envDirty > 0 && (
                    <span
                      className={`rounded-full px-1 text-[9px] font-extrabold ${
                        isActive
                          ? "bg-white/25 text-white"
                          : "bg-solar-orange/20 text-solar-red-orange"
                      }`}
                    >
                      {envDirty}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Project Paths & New Project */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={!activeProject}
              onClick={onOpenEditProject}
              title="Configure SBX/DEV/UAT/PROD repo paths for this project"
              className="btn btn-sm btn-secondary text-xs disabled:opacity-45"
            >
              <FolderCog className="h-3.5 w-3.5 text-bea-text-secondary" />
              <span className="hidden md:inline">Project Paths</span>
            </button>
            <button
              type="button"
              onClick={onOpenNewProject}
              title="Create a new multi-environment project"
              className="btn btn-sm btn-secondary text-xs"
            >
              <FolderPlus className="h-3.5 w-3.5 text-solar-red-orange" />
              <span className="hidden sm:inline">New Project</span>
            </button>
          </div>
        </div>

        {/* Right: Git Diff & Deploy / Promote */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!activeProject}
            onClick={() => onOpenGitDiff(activeEnv)}
            title={`Inspect ${activeEnv.toUpperCase()} git diff or compare environments`}
            className="btn btn-sm btn-secondary font-mono text-xs"
          >
            <GitBranch className="h-3.5 w-3.5 text-solar-red" />
            <span>Git Diff</span>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                dirtyCount > 0 || unpushedCount > 0
                  ? "bg-solar-orange/15 text-bea-burgundy"
                  : "bg-bea-emerald/15 text-bea-teal"
              }`}
            >
              {dirtyCount}M{unpushedCount > 0 ? ` ${unpushedCount}↑` : ""}
            </span>
          </button>

          <button
            type="button"
            disabled={!activeProject}
            onClick={() => onOpenDeploy(activeEnv)}
            title={`Commit, push, or promote changes to ${activeEnv.toUpperCase()}`}
            className="btn btn-sm btn-primary text-xs"
          >
            <Rocket className="h-3.5 w-3.5" />
            <span>Deploy / Promote</span>
          </button>
        </div>
      </div>

      {/* Row 2: Clean Environment Metadata Strip (Repo Path + Branch + Endpoint ONLY) */}
      {activeProject && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border border-bea-border bg-bea-canvas/65 px-3 py-1.5 text-xs">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0 font-semibold text-bea-text-secondary">
              Repo Path ({activeEnv.toUpperCase()}):
            </span>
            <code
              title={activePath}
              className="max-w-[360px] truncate font-mono font-semibold text-bea-text-strong"
            >
              {activePath || "Not configured"}
            </code>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-bea-text-secondary">Branch:</span>
            <code className="font-mono font-semibold text-bea-text-strong">
              {activeBranch || "no-git"}
            </code>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] font-bold ${
                dirtyCount > 0 || unpushedCount > 0
                  ? "border-solar-orange/50 bg-solar-yellow/15 text-bea-burgundy"
                  : "border-bea-emerald/40 bg-bea-emerald/10 text-bea-teal"
              }`}
            >
              {dirtyCount > 0 || unpushedCount > 0
                ? `${dirtyCount}M${unpushedCount > 0 ? ` · ${unpushedCount}↑` : ""}`
                : "Clean"}
            </span>
          </div>

          <div className="flex min-w-0 items-center gap-1.5">
            <span className="shrink-0 font-semibold text-bea-text-secondary">
              Endpoint:
            </span>
            {evalEndpoint ? (
              <code
                title={evalEndpoint}
                className="max-w-[360px] truncate font-mono font-semibold text-bea-blue"
              >
                {evalEndpoint}
              </code>
            ) : (
              <span className="italic text-bea-text-secondary">
                No endpoint configured on active eval suite
              </span>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
