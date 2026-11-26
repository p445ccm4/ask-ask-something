"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Lock, Rocket, ShieldCheck, X } from "lucide-react";
import { apiUrl } from "@/lib/basePath";
import {
  ENV_ORDER,
  type DeployMode,
  type DeployPreview,
  type DeployResult,
  type EnvName,
  type ProjectSummary,
  type TargetEnv,
} from "@/lib/types";
import { DiffViewer } from "./DiffViewer";

interface DeployModalProps {
  open: boolean;
  project: ProjectSummary | null;
  initialTargetEnv: TargetEnv;
  onClose: () => void;
  onDeployed: () => void;
}

export function DeployModal({
  open,
  project,
  initialTargetEnv,
  onClose,
  onDeployed,
}: DeployModalProps) {
  const configuredEnvs = project?.configured_envs || [];
  const [targetEnv, setTargetEnv] = useState<TargetEnv>(initialTargetEnv);
  const [sourceEnv, setSourceEnv] = useState<TargetEnv | "">("");
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<DeployPreview | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [includeConfigPy, setIncludeConfigPy] = useState(false);
  const [deployMode, setDeployMode] = useState<DeployMode>("auto");
  const [forceOverwrite, setForceOverwrite] = useState(false);
  const [commitMessage, setCommitMessage] = useState("");
  const commitMessageTouchedRef = useRef(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<DeployResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTargetEnv(
      configuredEnvs.includes(initialTargetEnv)
        ? initialTargetEnv
        : configuredEnvs[0] || "dev"
    );
    setSourceEnv("");
    setCommitMessage("");
    commitMessageTouchedRef.current = false;
    setIncludeConfigPy(false);
    setDeployMode("auto");
    setForceOverwrite(false);
    setResult(null);
    setError(null);
  }, [open, initialTargetEnv, project?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open || !project) return;
    let active = true;
    const loadPreview = async () => {
      setLoading(true);
      setError(null);
      setResult(null);
      try {
        const params = new URLSearchParams({
          target_env: targetEnv,
          include_config_py: String(includeConfigPy),
          deploy_mode: deployMode,
          force_overwrite: String(forceOverwrite),
        });
        if (sourceEnv && sourceEnv !== targetEnv) {
          params.set("source_env", sourceEnv);
        }
        const res = await fetch(
          apiUrl(
            `/api/projects/${encodeURIComponent(
              project.id
            )}/deploy/preview?${params.toString()}`
          )
        );
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Failed to load deploy preview");
        }
        if (!active) return;
        const prev = data as DeployPreview;
        setPreview(prev);
        setSelectedFiles(prev.changed_files.map((f) => f.path));
        if (!commitMessageTouchedRef.current) {
          setCommitMessage(prev.suggested_commit_message);
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) setLoading(false);
      }
    };
    void loadPreview();
    return () => {
      active = false;
    };
  }, [
    open,
    project,
    targetEnv,
    sourceEnv,
    includeConfigPy,
    deployMode,
    forceOverwrite,
  ]);

  if (!open || !project) return null;

  const toggleFile = (filePath: string) => {
    setSelectedFiles((prev) =>
      prev.includes(filePath)
        ? prev.filter((p) => p !== filePath)
        : [...prev, filePath]
    );
  };

  const handleDeploy = async () => {
    if (!preview || !preview.can_deploy) return;
    setExecuting(true);
    setError(null);
    try {
      const res = await fetch(
        apiUrl(`/api/projects/${encodeURIComponent(project.id)}/deploy/execute`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_env: targetEnv,
            source_env: sourceEnv || preview.source_env || undefined,
            commit_message: commitMessage,
            selected_files: selectedFiles,
            include_config_py: includeConfigPy,
            deploy_mode: deployMode,
            force_overwrite: forceOverwrite,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Deploy push failed");
      }
      setResult(data as DeployResult);
      onDeployed();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExecuting(false);
    }
  };

  const envLabel = targetEnv.toUpperCase();
  const availSources = (preview?.available_source_envs || []).filter(
    (e) => e !== targetEnv
  );
  const directConflictCount =
    preview?.direct_target_files?.length ??
    preview?.direct_uat_files?.length ??
    0;
  const directConflictFiles =
    preview?.direct_target_files ?? preview?.direct_uat_files ?? [];
  const canSubmit =
    Boolean(preview?.can_deploy) &&
    !executing &&
    !result &&
    (selectedFiles.length > 0 || (preview?.unpushed_commits.length ?? 0) > 0) &&
    (selectedFiles.length === 0 || commitMessage.trim().length > 0);

  return (
    <div className="animate-view-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-bea-border bg-bea-card shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-bea-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="white-on-solar flex h-9 w-9 items-center justify-center rounded-xl shadow-xs">
              <Rocket className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-bea-text-strong">
                Deploy / Promote {project.name} → {envLabel}
              </h2>
              <p className="text-xs text-bea-text-secondary">
                {targetEnv === "sbx"
                  ? "Stages scoped service files and pushes the Sandbox branch to origin."
                  : "Stages scoped service files and pushes to origin/main (with src/config.py protection)."}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-4 overflow-y-auto bg-bea-canvas/40 p-6">
          {/* Target Env + Mode Bar */}
          {!result && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bea-border bg-bea-card px-4 py-2.5 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-bea-text-secondary">
                  Target Env:
                </span>
                <div className="inline-flex rounded-lg border border-bea-border bg-bea-canvas p-0.5">
                  {ENV_ORDER.filter((e) => configuredEnvs.includes(e)).map(
                    (env) => (
                      <button
                        key={env}
                        type="button"
                        onClick={() => {
                          setTargetEnv(env);
                          setSourceEnv("");
                          setDeployMode("auto");
                          setForceOverwrite(false);
                          commitMessageTouchedRef.current = false;
                        }}
                        className={`cursor-pointer rounded-md px-2.5 py-1 text-[11px] font-bold uppercase transition ${
                          targetEnv === env
                            ? "bg-solar-red text-white shadow-2xs"
                            : "text-bea-text-secondary hover:text-bea-text-strong"
                        }`}
                      >
                        {env}
                      </button>
                    )
                  )}
                </div>
              </div>

              {availSources.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-semibold text-bea-text-secondary">
                    Mode:
                  </span>
                  {(
                    [
                      ["auto", "Auto"],
                      ["direct_push", `Push Direct ${envLabel}`],
                      ["promote", "Promote From"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => {
                        setDeployMode(value);
                        if (value !== "promote") setForceOverwrite(false);
                      }}
                      className={`cursor-pointer rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition ${
                        deployMode === value ||
                        (value === "promote" &&
                          deployMode === "promote_from_dev")
                          ? "border-bea-teal bg-bea-teal-solid text-white shadow-2xs"
                          : "border-bea-border bg-bea-canvas/60 text-bea-text-secondary hover:text-bea-text-strong"
                      }`}
                    >
                      {label}
                    </button>
                  ))}

                  {(deployMode === "promote" ||
                    deployMode === "auto" ||
                    preview?.mode === "promote" ||
                    preview?.mode === "promote_from_dev") && (
                    <select
                      value={sourceEnv || preview?.source_env || availSources[0] || ""}
                      onChange={(e) => {
                        setSourceEnv(e.target.value as EnvName);
                        setDeployMode("promote");
                      }}
                      aria-label="Promotion source environment"
                      className="rounded-lg border border-bea-border bg-bea-canvas px-2 py-1 text-[11px] font-bold uppercase text-bea-text-strong"
                    >
                      {availSources.map((src) => (
                        <option key={src} value={src}>
                          {src.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>
          )}

          {loading ? (
            <div className="py-12 text-center text-sm text-bea-text-secondary">
              Inspecting repository changes and computing {envLabel} diff preview...
            </div>
          ) : null}

          {error && (
            <div className="flex items-start gap-2.5 rounded-xl border border-solar-red/40 bg-bea-coral/25 p-3.5 text-xs text-bea-burgundy">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-solar-red" />
              <div className="whitespace-pre-wrap">{error}</div>
            </div>
          )}

          {result && (
            <div className="space-y-3 rounded-xl border border-bea-emerald/50 bg-bea-emerald/10 p-4">
              <div className="flex items-center gap-2 text-sm font-bold text-bea-teal">
                <CheckCircle2 className="h-5 w-5 text-bea-emerald" />
                Pushed to {envLabel} (<code>{result.branch}</code>
                {result.commit_sha ? ` @ ${result.commit_sha}` : ""})
              </div>
              {result.remote_url && (
                <p className="text-xs text-bea-text-primary">
                  Remote updated:{" "}
                  <code className="text-bea-blue">{result.remote_url}</code>
                </p>
              )}
              <pre className="max-h-56 overflow-auto rounded-lg border border-bea-border bg-bea-card p-3 font-mono text-[11px] text-bea-text-primary">
                {result.logs.join("\n")}
              </pre>
            </div>
          )}

          {preview && !result && (
            <>
              <div className="grid grid-cols-1 gap-3 rounded-xl border border-bea-border bg-bea-card p-4 text-xs sm:grid-cols-2">
                <div>
                  <span className="text-bea-text-secondary">Target Remote: </span>
                  <div className="mt-0.5 break-all font-mono text-bea-blue">
                    {preview.remote_url || "None"}
                  </div>
                </div>
                <div>
                  <span className="text-bea-text-secondary">
                    Scoped Path &amp; Branch:{" "}
                  </span>
                  <div className="mt-0.5 font-mono text-bea-text-strong">
                    {preview.service_subpath}/ ({preview.branch || "unknown"})
                    {preview.mode !== "direct_push" ? (
                      <span className="ml-2 select-none rounded bg-bea-emerald/15 px-1.5 py-0.5 text-[10px] font-semibold text-bea-teal">
                        {(preview.source_env || "SRC").toUpperCase()} → {envLabel} Promotion
                      </span>
                    ) : (
                      <span className="ml-2 select-none rounded bg-bea-teal/15 px-1.5 py-0.5 text-[10px] font-semibold text-bea-teal">
                        Direct {envLabel} Push
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {preview.mode !== "direct_push" &&
                (preview.has_direct_target_changes || preview.has_direct_uat_changes) &&
                directConflictCount > 0 && (
                  <div className="space-y-2 rounded-xl border border-solar-orange/45 bg-solar-yellow/15 p-3.5 text-xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-semibold text-bea-burgundy">
                        Direct uncommitted changes exist in {envLabel} ({directConflictCount}):{" "}
                        <code className="font-mono text-[11px]">
                          {directConflictFiles.join(", ")}
                        </code>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setDeployMode("direct_push");
                          setForceOverwrite(false);
                        }}
                        className="cursor-pointer rounded-lg border border-bea-emerald bg-bea-emerald px-2.5 py-1 text-[11px] font-semibold text-white transition hover:opacity-90"
                      >
                        Switch to Direct {envLabel} Push
                      </button>
                    </div>
                    {(preview.overlap_conflict_files?.length ?? 0) > 0 && (
                      <label className="flex cursor-pointer items-center gap-2 font-medium text-bea-burgundy">
                        <input
                          type="checkbox"
                          checked={forceOverwrite}
                          onChange={(e) => setForceOverwrite(e.target.checked)}
                          className="checkbox"
                        />
                        <span>
                          Overwrite overlapping direct {envLabel} edits (
                          <code className="font-mono">
                            {preview.overlap_conflict_files?.join(", ")}
                          </code>
                          ) with {(preview.source_env || "source").toUpperCase()} version
                        </span>
                      </label>
                    )}
                  </div>
                )}

              {preview.protected_files.length > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-bea-teal/30 bg-bea-teal/5 p-3.5 text-xs">
                  <div className="flex items-start gap-2.5">
                    <Lock className="mt-0.5 h-4 w-4 shrink-0 text-bea-teal" />
                    <div>
                      <div className="font-semibold text-bea-teal">
                        Protected {envLabel} Configuration Preserved
                      </div>
                      <p className="mt-0.5 text-bea-text-primary">
                        <code>src/config.py</code> differs between environments (PROJECT_ID &amp; GCS buckets) and is excluded automatically.
                      </p>
                    </div>
                  </div>
                  <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-[11px] font-medium text-bea-text-primary">
                    <input
                      type="checkbox"
                      checked={includeConfigPy}
                      onChange={(e) => setIncludeConfigPy(e.target.checked)}
                      className="checkbox"
                    />
                    Override &amp; include
                  </label>
                </div>
              )}

              {!preview.can_deploy && preview.blocking_reason && (
                <div className="flex items-center gap-2 rounded-xl border border-solar-orange/40 bg-solar-yellow/15 p-3.5 text-xs text-bea-burgundy">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-solar-red-orange" />
                  <span>{preview.blocking_reason}</span>
                </div>
              )}

              {preview.changed_files.length > 0 && (
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-bea-text-secondary">
                      Files to Stage &amp; Push ({selectedFiles.length}/
                      {preview.changed_files.length})
                    </h3>
                  </div>
                  <div className="max-h-40 space-y-1 overflow-y-auto rounded-xl border border-bea-border bg-bea-card p-2.5">
                    {preview.changed_files.map((f) => (
                      <label
                        key={f.path}
                        className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1 text-xs hover:bg-bea-canvas"
                      >
                        <input
                          type="checkbox"
                          checked={selectedFiles.includes(f.path)}
                          onChange={() => toggleFile(f.path)}
                          className="checkbox"
                        />
                        <span className="rounded bg-solar-orange/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-solar-red-orange">
                          {f.status}
                        </span>
                        <span className="font-mono text-bea-text-strong">
                          {f.path}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {preview.unpushed_commits.length > 0 && (
                <div className="rounded-xl border border-bea-border bg-bea-card p-3 text-xs">
                  <div className="font-semibold text-bea-text-strong">
                    Unpushed commits that will also be pushed:
                  </div>
                  <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-bea-text-secondary">
                    {preview.unpushed_commits.map((c, idx) => (
                      <li key={idx}>{c}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-bea-text-secondary">
                  Diff Preview
                </h3>
                <DiffViewer
                  diff={preview.diff}
                  emptyMessage="No file diffs (only existing unpushed commits will be pushed)."
                  maxHeightClass="max-h-60"
                />
              </div>

              {selectedFiles.length > 0 && (
                <div>
                  <label className="mb-1.5 block text-xs font-semibold text-bea-text-strong">
                    Commit Message
                  </label>
                  <input
                    type="text"
                    value={commitMessage}
                    onChange={(e) => {
                      commitMessageTouchedRef.current = true;
                      setCommitMessage(e.target.value);
                    }}
                    placeholder={`fix(${preview.service_subpath}): describe your fix`}
                    className="input text-sm"
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-bea-border bg-bea-card px-6 py-4">
          <div className="flex items-center gap-1.5 text-xs text-bea-text-secondary">
            <ShieldCheck className="h-4 w-4 text-bea-emerald" />
            <span>Sibling monorepo services are excluded from staging</span>
          </div>
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-secondary text-xs"
            >
              {result ? "Close" : "Cancel"}
            </button>
            {!result && (
              <button
                type="button"
                disabled={!canSubmit}
                onClick={handleDeploy}
                className="btn btn-primary text-xs"
              >
                <Rocket className="h-3.5 w-3.5" />
                {executing
                  ? "Committing & Pushing..."
                  : `Push to ${envLabel} (${preview?.branch || "main"})`}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
