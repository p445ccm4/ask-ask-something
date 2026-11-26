"use client";

import React, { useEffect, useState } from "react";
import { FileSpreadsheet, Upload, X } from "lucide-react";
import { apiUrl } from "@/lib/basePath";
import type { EnvName, InspectXlsxResponse } from "@/lib/types";

interface ImportXlsxModalProps {
  open: boolean;
  projectId: string;
  env: EnvName;
  activeSuiteId?: string | null;
  onClose: () => void;
  onImported: (suiteId: string) => void;
}

export function ImportXlsxModal({
  open,
  projectId,
  env,
  activeSuiteId,
  onClose,
  onImported,
}: ImportXlsxModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [inspectData, setInspectData] = useState<InspectXlsxResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [suiteName, setSuiteName] = useState("");
  const [targetSuiteMode, setTargetSuiteMode] = useState<"new" | "active">("new");
  const [replaceAll, setReplaceAll] = useState(true);

  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [groupBlankId, setGroupBlankId] = useState(false);
  const [colId, setColId] = useState("");
  const [colQuestion, setColQuestion] = useState("");
  const [colExpectedAnswer, setColExpectedAnswer] = useState("");
  const [colExpectedBehavior, setColExpectedBehavior] = useState("");
  const [colExpectedSource, setColExpectedSource] = useState("");
  const [colRemarks, setColRemarks] = useState("");

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setInspectData(null);
    setError(null);
    setSuiteName("");
    setTargetSuiteMode(activeSuiteId ? "new" : "new");
    setReplaceAll(true);
    setSheet("");
    setHeaderRow(1);
    setGroupBlankId(false);
    setColId("");
    setColQuestion("");
    setColExpectedAnswer("");
    setColExpectedBehavior("");
    setColExpectedSource("");
    setColRemarks("");
  }, [open, activeSuiteId]);

  if (!open) return null;

  const inspectFile = async (chosenFile: File, chosenSheet?: string) => {
    setInspecting(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", chosenFile);
      if (chosenSheet) fd.append("sheet", chosenSheet);
      const res = await fetch(
        apiUrl(`/api/projects/${encodeURIComponent(projectId)}/eval/inspect-xlsx`),
        { method: "POST", body: fd }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to inspect workbook");
      const parsed = data as InspectXlsxResponse;
      setInspectData(parsed);

      const sug = (parsed.suggested_mapping || {}) as Record<string, unknown>;
      const sugCols = (sug.columns || {}) as Record<string, unknown>;
      const chosenS = String(sug.sheet || parsed.sheets[0] || "");
      setSheet(chosenS);
      setHeaderRow(Number(sug.header_row || 1));
      setGroupBlankId(Boolean(sug.group_blank_id));
      setColId(String(sugCols.id || ""));
      setColQuestion(String(sugCols.question || ""));
      setColExpectedAnswer(String(sugCols.expected_answer || ""));
      setColExpectedBehavior(String(sugCols.expected_behavior || ""));
      setColExpectedSource(String(sugCols.expected_source || ""));
      setColRemarks(String(sugCols.remarks || ""));
      if (!suiteName.trim()) {
        setSuiteName(chosenFile.name.replace(/\.xlsx$/i, ""));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setInspecting(false);
    }
  };

  const handleFileChange = (chosen: File | null) => {
    if (!chosen) return;
    setFile(chosen);
    setSuiteName(chosen.name.replace(/\.xlsx$/i, ""));
    void inspectFile(chosen);
  };

  const activeSheetDetail =
    inspectData?.details.find((d) => d.name === sheet) ||
    inspectData?.details[0] ||
    null;
  const headerRowCells =
    activeSheetDetail?.sample_rows.find((r) => r.row === headerRow)?.cells ||
    activeSheetDetail?.sample_rows[0]?.cells ||
    {};
  const headerChoices = Object.values(headerRowCells).filter(Boolean);

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("Please select an .xlsx workbook first.");
      return;
    }
    if (!colQuestion.trim()) {
      setError("Question column mapping is required.");
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const baseSug = (inspectData?.suggested_mapping || {}) as Record<
        string,
        unknown
      >;
      const mapping = {
        ...baseSug,
        sheet: sheet || undefined,
        header_row: headerRow,
        group_blank_id: groupBlankId,
        columns: {
          id: colId.trim() || null,
          question: colQuestion.trim(),
          expected_answer: colExpectedAnswer.trim() || null,
          expected_behavior: colExpectedBehavior.trim() || null,
          expected_source: colExpectedSource.trim() || null,
          remarks: colRemarks.trim() || null,
        },
      };

      const fd = new FormData();
      fd.append("file", file);
      fd.append("env", env);
      if (targetSuiteMode === "active" && activeSuiteId) {
        fd.append("suite_id", activeSuiteId);
      } else if (suiteName.trim()) {
        fd.append("suite_name", suiteName.trim());
      }
      fd.append("mapping_json", JSON.stringify(mapping));
      fd.append("replace_all", String(replaceAll));

      const res = await fetch(
        apiUrl(`/api/projects/${encodeURIComponent(projectId)}/eval/import-xlsx`),
        { method: "POST", body: fd }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Excel import failed");
      onImported(data.suite?.id || activeSuiteId || "");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div
      onClick={() => {
        if (!importing) onClose();
      }}
      className="animate-view-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleImport}
        className="flex max-h-[92vh] w-full max-w-3xl flex-col gap-3.5 overflow-y-auto rounded-2xl border border-bea-border bg-bea-card p-6 shadow-2xl"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <FileSpreadsheet className="h-5 w-5 text-bea-emerald" />
            <div>
              <h3 className="text-base font-bold text-bea-text-strong">
                Import Excel (.xlsx) Eval Suite ({env.toUpperCase()})
              </h3>
              <p className="text-xs text-bea-text-secondary">
                Inspects columns, stores the template securely in workbench data, and imports cases into SQLite DB.
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

        {/* File Picker */}
        <label className="flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-bea-border bg-bea-canvas/55 px-4 py-5 text-center transition hover:border-solar-red">
          <Upload className="h-5 w-5 text-solar-red" />
          <div className="text-xs font-bold text-bea-text-strong">
            {file ? file.name : "Choose an .xlsx workbook to inspect"}
          </div>
          <div className="text-[11px] text-bea-text-secondary">
            {inspecting
              ? "Inspecting workbook sheets and columns..."
              : "Original file is stored in workbench .data/templates/ for formatted .xlsx export"}
          </div>
          <input
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files?.[0] || null)}
          />
        </label>

        {inspectData && (
          <>
            {/* Target Suite & Sheet Options */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Import Target
                </label>
                <select
                  value={targetSuiteMode}
                  onChange={(e) =>
                    setTargetSuiteMode(e.target.value as "new" | "active")
                  }
                  className="select text-xs"
                >
                  <option value="new">Create New Eval Suite</option>
                  {activeSuiteId && (
                    <option value="active">Update Active Suite</option>
                  )}
                </select>
              </div>
              {targetSuiteMode === "new" && (
                <div>
                  <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                    New Suite Name
                  </label>
                  <input
                    type="text"
                    value={suiteName}
                    onChange={(e) => setSuiteName(e.target.value)}
                    className="input text-xs"
                  />
                </div>
              )}
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Worksheet
                </label>
                <select
                  value={sheet}
                  onChange={(e) => {
                    setSheet(e.target.value);
                    if (file) void inspectFile(file, e.target.value);
                  }}
                  className="select text-xs"
                >
                  {inspectData.sheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-bea-text-strong">
                  Header Row #
                </label>
                <input
                  type="number"
                  min={1}
                  value={headerRow}
                  onChange={(e) => setHeaderRow(Math.max(1, Number(e.target.value) || 1))}
                  className="input text-xs"
                />
              </div>
              <div className="flex items-end pb-2 sm:col-span-3">
                <div className="flex flex-wrap gap-4">
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-bea-text-strong">
                    <input
                      type="checkbox"
                      checked={groupBlankId}
                      onChange={(e) => setGroupBlankId(e.target.checked)}
                      className="checkbox"
                    />
                    Group blank ID rows as multi-turn follow-ups
                  </label>
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-bea-text-strong">
                    <input
                      type="checkbox"
                      checked={replaceAll}
                      onChange={(e) => setReplaceAll(e.target.checked)}
                      className="checkbox"
                    />
                    Replace existing suite cases
                  </label>
                </div>
              </div>
            </div>

            {/* Column Mappings */}
            <datalist id="xlsx-header-choices">
              {headerChoices.map((h) => (
                <option key={h} value={h} />
              ))}
            </datalist>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              {[
                ["Case ID Column", colId, setColId, false],
                ["Question Column *", colQuestion, setColQuestion, true],
                ["Expected Answer", colExpectedAnswer, setColExpectedAnswer, false],
                ["Expected Behavior", colExpectedBehavior, setColExpectedBehavior, false],
                ["Expected Source", colExpectedSource, setColExpectedSource, false],
                ["Remarks / Notes", colRemarks, setColRemarks, false],
              ].map(([label, val, setter, req]) => (
                <div key={label as string}>
                  <label className="mb-1 block text-[11px] font-semibold text-bea-text-secondary">
                    {label as string}
                  </label>
                  <input
                    type="text"
                    required={Boolean(req)}
                    list="xlsx-header-choices"
                    value={val as string}
                    onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                    placeholder="Header name or letter (e.g. B)"
                    className="input text-xs"
                  />
                </div>
              ))}
            </div>

            {/* Sample Row Preview */}
            {activeSheetDetail && activeSheetDetail.sample_rows.length > 0 && (
              <div className="rounded-xl border border-bea-border bg-bea-canvas/50 p-3">
                <div className="mb-1.5 text-[11px] font-bold uppercase text-bea-text-secondary">
                  Preview ({activeSheetDetail.non_empty_rows} non-empty rows)
                </div>
                <div className="max-h-36 overflow-auto text-[11px]">
                  <table className="w-full border-collapse text-left">
                    <tbody>
                      {activeSheetDetail.sample_rows.slice(0, 5).map((sr) => (
                        <tr key={sr.row} className="border-b border-bea-border/60">
                          <td className="pr-2 font-mono font-bold text-bea-text-secondary">
                            R{sr.row}
                          </td>
                          {Object.entries(sr.cells)
                            .slice(0, 6)
                            .map(([col, text]) => (
                              <td
                                key={col}
                                className="max-w-[160px] truncate px-2 py-1 text-bea-text-strong"
                                title={text}
                              >
                                <span className="mr-1 font-mono text-[10px] text-bea-text-secondary">
                                  {col}:
                                </span>
                                {text}
                              </td>
                            ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}

        <div className="flex justify-end gap-2 border-t border-bea-border pt-3">
          <button
            type="button"
            onClick={onClose}
            disabled={importing}
            className="btn btn-secondary text-xs"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={importing || inspecting || !file || !inspectData}
            className="btn btn-solar text-xs"
          >
            {importing ? "Importing to SQLite..." : "Import Eval Cases"}
          </button>
        </div>
      </form>
    </div>
  );
}
