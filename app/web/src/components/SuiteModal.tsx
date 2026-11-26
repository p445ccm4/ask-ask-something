"use client";

import React, { useEffect, useState } from "react";
import { Settings2, Trash2, X } from "lucide-react";
import { apiUrl } from "@/lib/basePath";
import type { EnvName, EvalSuiteFull } from "@/lib/types";

interface SuiteModalProps {
  open: boolean;
  mode: "create" | "edit";
  projectId: string;
  env: EnvName;
  suiteId?: string | null;
  onClose: () => void;
  onSaved: (suiteId: string) => void;
  onDeleted?: (suiteId: string) => void;
}

export function SuiteModal({
  open,
  mode,
  projectId,
  env,
  suiteId,
  onClose,
  onSaved,
  onDeleted,
}: SuiteModalProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [authMode, setAuthMode] = useState("none");
  const [responseMode, setResponseMode] = useState("sse");
  const [judgeModel, setJudgeModel] = useState("gemini-2.5-flash");
  const [judgeProjectId, setJudgeProjectId] = useState("");
  const [judgeLocation, setJudgeLocation] = useState("global");
  const [rubricMd, setRubricMd] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [extraConfig, setExtraConfig] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmDelete(false);
    if (mode === "edit" && suiteId && projectId) {
      let active = true;
      setLoading(true);
      fetch(
        apiUrl(
          `/api/projects/${encodeURIComponent(projectId)}/eval/suites/${encodeURIComponent(
            suiteId
          )}`
        )
      )
        .then(async (res) => {
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || "Failed to load eval suite");
          return data.suite as EvalSuiteFull;
        })
        .then((s) => {
          if (!active) return;
          const cfg = (s.config || {}) as Record<string, unknown>;
          const authCfg = (cfg.auth || {}) as Record<string, unknown>;
          const respCfg = (cfg.response || {}) as Record<string, unknown>;
          const judgeCfg = (cfg.judge || {}) as Record<string, unknown>;
          setName(s.name || "");
          setDescription(s.description || "");
          setEndpoint(String(cfg.endpoint || ""));
          setAuthMode(String(authCfg.mode || "none"));
          setResponseMode(String(respCfg.mode || "sse"));
          setJudgeModel(String(judgeCfg.model || "gemini-2.5-flash"));
          setJudgeProjectId(String(judgeCfg.project_id || ""));
          setJudgeLocation(String(judgeCfg.location || "global"));
          setRubricMd(s.rubric_md || "");
          setIsDefault(Boolean(s.is_default));
          setExtraConfig(cfg);
        })
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
      };
    }

    setLoading(false);
    setName("");
    setDescription("");
    setEndpoint("");
    setAuthMode("none");
    setResponseMode("sse");
    setJudgeModel("gemini-2.5-flash");
    setJudgeProjectId("");
    setJudgeLocation("global");
    setRubricMd("");
    setIsDefault(false);
    setExtraConfig({});
  }, [open, mode, suiteId, projectId]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Suite name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const nextConfig: Record<string, unknown> = {
        ...extraConfig,
        endpoint: endpoint.trim(),
        auth: {
          ...((extraConfig.auth as Record<string, unknown>) || {}),
          mode: authMode,
        },
        response: {
          ...((extraConfig.response as Record<string, unknown>) || {}),
          mode: responseMode,
        },
        judge: {
          ...((extraConfig.judge as Record<string, unknown>) || {}),
          model: judgeModel.trim() || "gemini-2.5-flash",
          location: judgeLocation.trim() || "global",
          ...(judgeProjectId.trim()
            ? { project_id: judgeProjectId.trim() }
            : {}),
        },
      };

      const isEdit = mode === "edit" && Boolean(suiteId);
      const url = isEdit
        ? apiUrl(
            `/api/projects/${encodeURIComponent(
              projectId
            )}/eval/suites/${encodeURIComponent(suiteId!)}`
          )
        : apiUrl(`/api/projects/${encodeURIComponent(projectId)}/eval/suites`);
      const res = await fetch(url, {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(isEdit ? {} : { env }),
          name: name.trim(),
          description: description.trim(),
          config: nextConfig,
          rubric_md: rubricMd,
          is_default: isDefault,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to save eval suite");
      onSaved(data.suite?.id || suiteId || "");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!suiteId) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(
        apiUrl(
          `/api/projects/${encodeURIComponent(
            projectId
          )}/eval/suites/${encodeURIComponent(suiteId)}`
        ),
        { method: "DELETE" }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to delete eval suite");
      onDeleted?.(suiteId);
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
        className="flex max-h-[92vh] w-full max-w-2xl flex-col gap-3.5 overflow-y-auto rounded-2xl border border-bea-border bg-bea-card p-6 shadow-2xl"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <Settings2 className="h-5 w-5 text-solar-red" />
            <div>
              <h3 className="text-base font-bold text-bea-text-strong">
                {mode === "edit" ? "Eval Suite Settings" : "Create Eval Suite"} (
                {env.toUpperCase()})
              </h3>
              <p className="text-xs text-bea-text-secondary">
                Stored centrally in SQLite DB — zero files written to target repo.
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

        {error && (
          <div className="rounded-lg border border-solar-red/40 bg-bea-coral/25 p-2.5 text-xs text-bea-burgundy">
            {error}
          </div>
        )}

        {loading ? (
          <div className="py-10 text-center text-xs text-bea-text-secondary">
            Loading eval suite configuration...
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Suite Name *
                </label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Core Policy Regression"
                  className="input text-xs"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Description
                </label>
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Short description of what this suite tests"
                  className="input text-xs"
                />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                Agent Endpoint URL
              </label>
              <input
                type="url"
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                placeholder="https://service-url.run.app/chat"
                className="input font-mono text-xs"
              />
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Auth Mode
                </label>
                <select
                  value={authMode}
                  onChange={(e) => setAuthMode(e.target.value)}
                  className="select text-xs"
                >
                  <option value="none">None</option>
                  <option value="gcloud-id-token">GCP ID Token</option>
                  <option value="bearer-env">Bearer Env</option>
                  <option value="header-env">Header Env</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Response Mode
                </label>
                <select
                  value={responseMode}
                  onChange={(e) => setResponseMode(e.target.value)}
                  className="select text-xs"
                >
                  <option value="sse">SSE Stream</option>
                  <option value="json">JSON</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Judge Model
                </label>
                <input
                  type="text"
                  value={judgeModel}
                  onChange={(e) => setJudgeModel(e.target.value)}
                  className="input font-mono text-xs"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Judge Location
                </label>
                <input
                  type="text"
                  value={judgeLocation}
                  onChange={(e) => setJudgeLocation(e.target.value)}
                  className="input font-mono text-xs"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Vertex Judge Project ID (optional)
                </label>
                <input
                  type="text"
                  value={judgeProjectId}
                  onChange={(e) => setJudgeProjectId(e.target.value)}
                  placeholder="Defaults to active gcloud / GOOGLE_CLOUD_PROJECT"
                  className="input font-mono text-xs"
                />
              </div>
              <div className="flex items-end pb-2">
                <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-bea-text-strong">
                  <input
                    type="checkbox"
                    checked={isDefault}
                    onChange={(e) => setIsDefault(e.target.checked)}
                    className="checkbox"
                  />
                  Set as default suite for {env.toUpperCase()}
                </label>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                Domain Judge Rubric (Markdown)
              </label>
              <textarea
                rows={5}
                value={rubricMd}
                onChange={(e) => setRubricMd(e.target.value)}
                placeholder="Domain-specific evaluation criteria for LLM-as-a-Judge..."
                className="w-full rounded-lg border border-bea-border bg-bea-card p-2.5 font-mono text-xs text-bea-text-strong focus:border-solar-red focus:outline-none"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-bea-border pt-3">
              <div>
                {mode === "edit" && suiteId && onDeleted && (
                  confirmDelete ? (
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-bea-burgundy">
                        Delete suite &amp; results?
                      </span>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={handleDelete}
                        className="btn btn-sm btn-danger"
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => setConfirmDelete(false)}
                        className="btn btn-sm btn-secondary"
                      >
                        Cancel
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
                      Delete Suite
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
                  disabled={saving}
                  className="btn btn-solar text-xs"
                >
                  {saving
                    ? "Saving..."
                    : mode === "edit"
                    ? "Save Suite Settings"
                    : "Create Suite"}
                </button>
              </div>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
