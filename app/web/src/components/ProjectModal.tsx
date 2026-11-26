"use client";

import React, { useCallback, useEffect, useState } from "react";
import { FolderCog, FolderPlus, Trash2, X } from "lucide-react";
import {
  FolderBrowser,
  type BrowseFolderItem,
} from "@ag-workbench/index";
import { apiUrl } from "@/lib/basePath";
import { ENV_LABELS, ENV_ORDER, type EnvName, type ProjectSummary } from "@/lib/types";

export interface ProjectModalProps {
  open: boolean;
  mode: "create" | "edit";
  project?: ProjectSummary | null;
  onClose: () => void;
  onSaveProject: (payload: {
    projectId?: string;
    name: string;
    environments: Partial<Record<EnvName, string>>;
    active_env: EnvName;
  }) => Promise<void>;
  onDeleteProject?: (projectId: string) => Promise<void>;
}

const API_ROOT = apiUrl("/api");

const ENV_BADGE_CLASSES: Record<EnvName, string> = {
  sbx: "bg-bea-canvas text-bea-text-strong border-bea-border",
  dev: "bg-bea-blue/15 text-bea-blue border-bea-blue/35",
  uat: "bg-solar-orange/15 text-solar-red-orange border-solar-orange/40",
  prod: "bg-bea-emerald/15 text-bea-teal border-bea-emerald/40",
};

function inferProjectName(envs: Partial<Record<EnvName, string>>): string {
  for (const env of ENV_ORDER) {
    const val = (envs[env] || "").trim();
    if (!val) continue;
    const tail = val.split("/").filter(Boolean).pop();
    if (tail) return tail;
  }
  return "New Project";
}

export function ProjectModal({
  open,
  mode,
  project,
  onClose,
  onSaveProject,
  onDeleteProject,
}: ProjectModalProps) {
  const [name, setName] = useState("");
  const [autoFilledName, setAutoFilledName] = useState("");
  const [envPaths, setEnvPaths] = useState<Record<EnvName, string>>({
    sbx: "",
    dev: "",
    uat: "",
    prod: "",
  });
  const [activeTarget, setActiveTarget] = useState<EnvName>("dev");
  const [defaultEnv, setDefaultEnv] = useState<EnvName>("dev");

  const [browseTargetPath, setBrowseTargetPath] = useState<string | undefined>(
    undefined
  );
  const [browseTrigger, setBrowseTrigger] = useState(0);

  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    if (mode === "edit" && project) {
      setName(project.name);
      setAutoFilledName("");
      const nextPaths: Record<EnvName, string> = {
        sbx: project.environments.sbx || "",
        dev: project.environments.dev || "",
        uat: project.environments.uat || "",
        prod: project.environments.prod || "",
      };
      setEnvPaths(nextPaths);
      const initialTarget = project.active_env || project.configured_envs[0] || "dev";
      setActiveTarget(initialTarget);
      setDefaultEnv(initialTarget);
      setBrowseTargetPath(nextPaths[initialTarget] || undefined);
      setBrowseTrigger((n) => n + 1);
    } else {
      setName("");
      setAutoFilledName("");
      setEnvPaths({ sbx: "", dev: "", uat: "", prod: "" });
      setActiveTarget("dev");
      setDefaultEnv("dev");
      setBrowseTargetPath(undefined);
      setBrowseTrigger(0);
    }
  }, [open, mode, project]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, saving, onClose]);

  const navigateBrowserTo = useCallback((env: EnvName, pathValue: string) => {
    setActiveTarget(env);
    const trimmed = pathValue.trim();
    if (trimmed) {
      setBrowseTargetPath(trimmed);
      setBrowseTrigger((n) => n + 1);
    } else {
      setBrowseTargetPath(undefined);
      setBrowseTrigger((n) => n + 1);
    }
  }, []);

  const handleSelectPath = useCallback(
    (folderPath: string, folderName: string) => {
      setEnvPaths((prev) => ({ ...prev, [activeTarget]: folderPath }));
      if (!name.trim() || name === autoFilledName) {
        setName(folderName);
        setAutoFilledName(folderName);
      }
    },
    [activeTarget, name, autoFilledName]
  );

  const renderFolderBadges = useCallback(
    (folder: BrowseFolderItem) => {
      const matched = ENV_ORDER.filter(
        (env) => envPaths[env].trim() === folder.path
      );
      if (matched.length === 0) return null;
      return (
        <>
          {matched.map((env) => (
            <span
              key={env}
              className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${ENV_BADGE_CLASSES[env]}`}
            >
              {env}
            </span>
          ))}
        </>
      );
    },
    [envPaths]
  );

  if (!open) return null;

  const configuredCount = ENV_ORDER.filter((e) => envPaths[e].trim().length > 0).length;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned: Partial<Record<EnvName, string>> = {};
    for (const env of ENV_ORDER) {
      const v = envPaths[env].trim();
      if (v) cleaned[env] = v;
    }
    if (Object.keys(cleaned).length === 0) {
      setError("Please enter or select at least one environment repository path.");
      return;
    }
    const chosenEnv: EnvName = cleaned[defaultEnv]
      ? defaultEnv
      : (ENV_ORDER.find((env) => Boolean(cleaned[env])) as EnvName);
    const targetName = name.trim() || inferProjectName(cleaned);

    setSaving(true);
    setError(null);
    try {
      await onSaveProject({
        projectId: mode === "edit" ? project?.id : undefined,
        name: targetName,
        environments: cleaned,
        active_env: chosenEnv,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!project || !onDeleteProject) return;
    setSaving(true);
    setError(null);
    try {
      await onDeleteProject(project.id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      onClick={() => {
        if (!saving) onClose();
      }}
      className="animate-view-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="flex max-h-[92vh] w-full max-w-3xl flex-col gap-3.5 overflow-y-auto rounded-2xl border border-bea-border bg-bea-card p-6 shadow-2xl"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            {mode === "edit" ? (
              <FolderCog className="h-5 w-5 text-solar-red" />
            ) : (
              <FolderPlus className="h-5 w-5 text-solar-red" />
            )}
            <div>
              <h3 className="text-base font-bold text-bea-text-strong">
                {mode === "edit"
                  ? `Project Paths — ${project?.name || ""}`
                  : "Create New Project"}
              </h3>
              <p className="text-xs text-bea-text-secondary">
                Map local repositories for SBX, DEV, UAT, and PROD. At least one repo path is required.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            aria-label="Close modal"
            className="inline-flex cursor-pointer items-center justify-center rounded-lg border border-bea-border p-1.5 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-solar-red/40 bg-bea-coral/25 p-2.5 text-xs text-bea-burgundy">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
              Project Name *
            </label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. AskHR, AskLegal"
              className="input text-xs"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
              Active Environment
            </label>
            <select
              value={defaultEnv}
              onChange={(e) => setDefaultEnv(e.target.value as EnvName)}
              className="select text-xs font-semibold"
            >
              {ENV_ORDER.map((env) => (
                <option
                  key={env}
                  value={env}
                  disabled={configuredCount > 0 && !envPaths[env].trim()}
                >
                  {env.toUpperCase()} ({ENV_LABELS[env]})
                  {!envPaths[env].trim() ? " — empty" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Target environment selector for FolderBrowser */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-bea-border bg-bea-canvas/60 px-3 py-2 text-xs">
          <span className="font-semibold text-bea-text-secondary">
            Browsing directory for:
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            {ENV_ORDER.map((env) => {
              const isSelected = activeTarget === env;
              const hasValue = Boolean(envPaths[env].trim());
              return (
                <button
                  key={env}
                  type="button"
                  onClick={() => setActiveTarget(env)}
                  className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-bold uppercase transition ${
                    isSelected
                      ? "border-solar-red bg-solar-red text-white shadow-2xs"
                      : "border-bea-border bg-bea-card text-bea-text-primary hover:text-bea-text-strong"
                  }`}
                >
                  <span>{env}</span>
                  {hasValue && (
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        isSelected ? "bg-white" : "bg-bea-emerald"
                      }`}
                    />
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <FolderBrowser
          apiBase={API_ROOT}
          browsePath={browseTargetPath}
          browseTrigger={browseTrigger}
          selectedPath={envPaths[activeTarget]}
          highlightTone={activeTarget === "uat" || activeTarget === "prod" ? "teal" : "brand"}
          renderFolderBadges={renderFolderBadges}
          useCurrentFolderLabel={`Use Current Folder (${activeTarget.toUpperCase()})`}
          onSelectPath={handleSelectPath}
          maxHeightClass="max-h-48"
        />

        {/* 4 Environment Path Inputs */}
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {ENV_ORDER.map((env) => {
            const isActiveField = activeTarget === env;
            const val = envPaths[env];
            return (
              <div
                key={env}
                className={`rounded-xl border p-2.5 transition ${
                  isActiveField
                    ? "border-solar-red/60 bg-solar-red/5"
                    : "border-bea-border bg-bea-card"
                }`}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <label className="flex items-center gap-1.5 text-[11px] font-bold uppercase text-bea-text-strong">
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[10px] ${ENV_BADGE_CLASSES[env]}`}
                    >
                      {env}
                    </span>
                    <span>{ENV_LABELS[env]} Repo</span>
                  </label>
                  {isActiveField && (
                    <span className="text-[10px] font-semibold text-solar-red">
                      Picking above
                    </span>
                  )}
                </div>
                <div className="flex gap-1.5">
                  <input
                    type="text"
                    value={val}
                    onFocus={() => setActiveTarget(env)}
                    onChange={(e) =>
                      setEnvPaths((prev) => ({ ...prev, [env]: e.target.value }))
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        navigateBrowserTo(env, val);
                      }
                    }}
                    placeholder={`/path/to/${env}/service`}
                    className="min-w-0 flex-1 rounded-lg border border-bea-border bg-bea-card px-2.5 py-1.5 font-mono text-xs text-bea-text-strong focus:border-solar-red focus:outline-none"
                  />
                  {val.trim() && (
                    <button
                      type="button"
                      onClick={() =>
                        setEnvPaths((prev) => ({ ...prev, [env]: "" }))
                      }
                      title={`Clear ${env.toUpperCase()} path`}
                      className="shrink-0 cursor-pointer rounded-lg border border-bea-border bg-bea-card px-2 py-1 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => navigateBrowserTo(env, val)}
                    className="shrink-0 cursor-pointer rounded-lg border border-bea-border bg-bea-canvas/70 px-2 py-1 text-[11px] font-semibold text-bea-text-strong hover:bg-bea-canvas"
                  >
                    {val.trim() ? "Go" : "Browse"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-bea-border pt-3">
          <div>
            {mode === "edit" && project && onDeleteProject && (
              confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-bea-burgundy">
                    Delete project &amp; its DB eval data?
                  </span>
                  <button
                    type="button"
                    disabled={saving}
                    onClick={handleDelete}
                    className="btn btn-sm btn-danger"
                  >
                    Confirm Delete
                  </button>
                  <button
                    type="button"
                    disabled={saving}
                    onClick={() => setConfirmDelete(false)}
                    className="btn btn-sm btn-secondary"
                  >
                    Keep
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => setConfirmDelete(true)}
                  className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-solar-red/30 px-2.5 py-1.5 text-xs font-semibold text-bea-burgundy hover:bg-bea-coral/20"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete Project
                </button>
              )
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="btn btn-secondary text-xs"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || configuredCount === 0}
              className="btn btn-solar text-xs"
            >
              {saving
                ? "Saving..."
                : mode === "edit"
                ? "Save Project Paths"
                : "Create Project"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
