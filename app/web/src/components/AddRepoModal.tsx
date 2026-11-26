"use client";

import React, { useCallback, useEffect, useState } from "react";
import { FolderPlus, X } from "lucide-react";
import {
  FolderBrowser,
  type BrowseFolderItem,
} from "@ag-workbench/index";
import { apiUrl } from "@/lib/basePath";

type PathTarget = "dev" | "uat";

export interface AddRepoModalProps {
  open: boolean;
  onClose: () => void;
  onAddWorkspace: (payload: {
    name: string;
    path: string;
    uat_path?: string;
  }) => Promise<void>;
}

const API_ROOT = apiUrl("/api");

function folderNameFromPath(targetPath: string): string {
  const trimmed = targetPath.trim();
  if (!trimmed) return "workspace";
  if (trimmed === "/") return "root";
  return trimmed.split("/").filter(Boolean).pop() || "workspace";
}

export function AddRepoModal({
  open,
  onClose,
  onAddWorkspace,
}: AddRepoModalProps) {
  const [repoName, setRepoName] = useState("");
  const [autoFilledName, setAutoFilledName] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [uatPath, setUatPath] = useState("");
  const [activeTarget, setActiveTarget] = useState<PathTarget>("dev");

  const [browseTargetPath, setBrowseTargetPath] = useState<string | undefined>(
    undefined
  );
  const [browseTrigger, setBrowseTrigger] = useState(0);

  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setAddError(null);
    setRepoName("");
    setAutoFilledName("");
    setRepoPath("");
    setUatPath("");
    setActiveTarget("dev");
    setBrowseTargetPath(undefined);
    setBrowseTrigger(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !adding) {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, adding, onClose]);

  const navigateBrowserTo = useCallback((target: PathTarget, pathValue: string) => {
    setActiveTarget(target);
    const trimmed = pathValue.trim();
    if (trimmed) {
      setBrowseTargetPath(trimmed);
      setBrowseTrigger((n) => n + 1);
    } else if (target === "dev") {
      setBrowseTargetPath(undefined);
      setBrowseTrigger((n) => n + 1);
    }
  }, []);

  const handleSelectPath = useCallback(
    (folderPath: string, folderName: string) => {
      if (activeTarget === "uat") {
        setUatPath(folderPath);
        return;
      }
      setRepoPath(folderPath);
      if (!repoName.trim() || repoName === autoFilledName) {
        setRepoName(folderName);
        setAutoFilledName(folderName);
      }
    },
    [activeTarget, repoName, autoFilledName]
  );

  const renderFolderBadges = useCallback(
    (folder: BrowseFolderItem) => {
      const isDevSelected = repoPath.trim() === folder.path;
      const isUatSelected = uatPath.trim() === folder.path;
      return (
        <>
          {isDevSelected && (
            <span className="shrink-0 rounded bg-ag-coral/25 px-1.5 py-0.5 text-[10px] font-bold text-ag-error-text">
              DEV
            </span>
          )}
          {isUatSelected && (
            <span className="shrink-0 rounded bg-ag-emerald/20 px-1.5 py-0.5 text-[10px] font-bold text-ag-teal">
              UAT
            </span>
          )}
        </>
      );
    },
    [repoPath, uatPath]
  );

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const targetPath = repoPath.trim();
    if (!targetPath) {
      setAddError("Please select or enter a local DEV repository path.");
      return;
    }
    const targetName = repoName.trim() || folderNameFromPath(targetPath);

    setAdding(true);
    setAddError(null);
    try {
      await onAddWorkspace({
        name: targetName,
        path: targetPath,
        uat_path: uatPath.trim() || undefined,
      });
      onClose();
    } catch (err) {
      setAddError(err instanceof Error ? err.message : String(err));
    } finally {
      setAdding(false);
    }
  };

  return (
    <div
      onClick={() => {
        if (!adding) onClose();
      }}
      className="animate-view-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="flex max-h-[92vh] w-full max-w-2xl flex-col gap-3.5 overflow-hidden rounded-2xl border border-ag-border bg-ag-card p-6 shadow-2xl"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <FolderPlus className="h-4 w-4 text-ag-red" />
            <h3 className="text-base font-bold text-ag-text-strong">
              Add Agent Repository
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={adding}
            aria-label="Close modal"
            className="inline-flex cursor-pointer items-center justify-center rounded-lg border border-ag-border p-1 text-ag-text-secondary hover:bg-ag-canvas hover:text-ag-text-strong disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {addError && (
          <div className="rounded-lg border border-ag-red/40 bg-ag-coral/25 p-2.5 text-xs text-ag-error-text">
            {addError}
          </div>
        )}

        {/* Target field selector for folder browser */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-ag-border bg-ag-canvas/50 px-3 py-2 text-xs">
          <span className="font-semibold text-ag-text-secondary">
            Browsing folder for:
          </span>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setActiveTarget("dev")}
              className={`cursor-pointer rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition ${
                activeTarget === "dev"
                  ? "border-ag-red bg-ag-coral/20 text-ag-text-strong"
                  : "border-ag-border bg-ag-card text-ag-text-secondary hover:text-ag-text-strong"
              }`}
            >
              DEV Repository Path *
            </button>
            <button
              type="button"
              onClick={() => setActiveTarget("uat")}
              className={`cursor-pointer rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition ${
                activeTarget === "uat"
                  ? "border-ag-teal bg-ag-emerald/15 text-ag-text-strong"
                  : "border-ag-border bg-ag-card text-ag-text-secondary hover:text-ag-text-strong"
              }`}
            >
              Paired UAT Path (Optional)
            </button>
          </div>
        </div>

        <FolderBrowser
          apiBase={API_ROOT}
          browsePath={browseTargetPath}
          browseTrigger={browseTrigger}
          selectedPath={activeTarget === "dev" ? repoPath : uatPath}
          highlightTone={activeTarget === "uat" ? "teal" : "brand"}
          renderFolderBadges={renderFolderBadges}
          useCurrentFolderLabel={`Use Current Folder (${activeTarget.toUpperCase()})`}
          onSelectPath={handleSelectPath}
          maxHeightClass="max-h-52"
        />

        {/* Selected paths & Display Name */}
        <div className="space-y-2.5">
          <div>
            <label className="mb-1 block text-xs font-semibold text-ag-text-primary">
              Display Name
            </label>
            <input
              type="text"
              required
              value={repoName}
              onChange={(e) => setRepoName(e.target.value)}
              placeholder="e.g. Sample Agent (DEV)"
              className="w-full rounded-lg border border-ag-border bg-ag-card px-3 py-2 text-xs text-ag-text-strong focus:border-ag-red focus:outline-none"
            />
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <label className="block text-xs font-semibold text-ag-text-primary">
                Local DEV Repository / Service Path
              </label>
              {activeTarget === "dev" && (
                <span className="text-[10px] font-semibold text-ag-red">
                  Picking in browser above
                </span>
              )}
            </div>
            <div className="flex gap-1.5">
              <input
                type="text"
                required
                value={repoPath}
                onFocus={() => setActiveTarget("dev")}
                onChange={(e) => setRepoPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    navigateBrowserTo("dev", repoPath);
                  }
                }}
                placeholder="Click a folder above or enter /path/to/dev-repo/service"
                className={`min-w-0 flex-1 rounded-lg border bg-ag-card px-3 py-2 font-mono text-xs text-ag-text-strong focus:outline-none ${
                  activeTarget === "dev"
                    ? "border-ag-red ring-1 ring-ag-red/25"
                    : "border-ag-border focus:border-ag-red"
                }`}
              />
              <button
                type="button"
                onClick={() => navigateBrowserTo("dev", repoPath)}
                title="Browse DEV path"
                className="shrink-0 cursor-pointer rounded-lg border border-ag-border bg-ag-canvas/70 px-2.5 py-2 text-[11px] font-semibold text-ag-text-strong hover:bg-ag-canvas"
              >
                {repoPath.trim() ? "Go" : "Browse"}
              </button>
            </div>
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <label className="block text-xs font-semibold text-ag-text-primary">
                Optional Paired UAT Path (agent-editable &amp; Deploy to UAT)
              </label>
              {activeTarget === "uat" && (
                <span className="text-[10px] font-semibold text-ag-teal">
                  Picking in browser above
                </span>
              )}
            </div>
            <div className="flex gap-1.5">
              <input
                type="text"
                value={uatPath}
                onFocus={() => setActiveTarget("uat")}
                onChange={(e) => setUatPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    navigateBrowserTo("uat", uatPath);
                  }
                }}
                placeholder="Optional: switch to Paired UAT above and click a folder"
                className={`min-w-0 flex-1 rounded-lg border bg-ag-card px-3 py-2 font-mono text-xs text-ag-text-strong focus:outline-none ${
                  activeTarget === "uat"
                    ? "border-ag-teal ring-1 ring-ag-teal/25"
                    : "border-ag-border focus:border-ag-teal"
                }`}
              />
              {uatPath.trim() && (
                <button
                  type="button"
                  onClick={() => setUatPath("")}
                  title="Clear paired UAT path"
                  aria-label="Clear paired UAT path"
                  className="shrink-0 cursor-pointer rounded-lg border border-ag-border bg-ag-card px-2 py-2 text-ag-text-secondary hover:bg-ag-canvas hover:text-ag-text-strong"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                type="button"
                onClick={() => navigateBrowserTo("uat", uatPath)}
                title="Browse for paired UAT path"
                className="shrink-0 cursor-pointer rounded-lg border border-ag-border bg-ag-canvas/70 px-2.5 py-2 text-[11px] font-semibold text-ag-text-strong hover:bg-ag-canvas"
              >
                {uatPath.trim() ? "Go" : "Browse"}
              </button>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={adding}
            className="cursor-pointer rounded-lg border border-ag-border px-3.5 py-2 text-xs font-medium text-ag-text-primary hover:bg-ag-canvas disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={adding || !repoPath.trim()}
            className="ag-white-on-solar cursor-pointer rounded-lg px-4 py-2 text-xs font-semibold shadow-sm transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {adding ? "Adding..." : "Add Repository"}
          </button>
        </div>
      </form>
    </div>
  );
}
