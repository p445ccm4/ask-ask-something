"use client";

import React, { useState } from "react";
import { Check, FileEdit, ShieldAlert, Terminal, X } from "lucide-react";
import type { PendingApprovalItem } from "@/lib/types";

interface ApprovalCardProps {
  approval: PendingApprovalItem;
  onDecide: (approvalId: string, approved: boolean) => Promise<void>;
}

export function ApprovalCard({ approval, onDecide }: ApprovalCardProps) {
  const [submitting, setSubmitting] = useState(false);

  const handleClick = async (approved: boolean) => {
    if (submitting || approval.status !== "pending") return;
    setSubmitting(true);
    try {
      await onDecide(approval.approval_id, approved);
    } finally {
      setSubmitting(false);
    }
  };

  const cmdLine =
    (approval.args?.command_line as string | undefined) ||
    (approval.args?.CommandLine as string | undefined);
  const targetFile =
    (approval.args?.TargetFile as string | undefined) ||
    (approval.args?.target_file as string | undefined) ||
    (approval.args?.path as string | undefined);

  const isCommand = approval.tool_name === "run_command";

  return (
    <div
      className={`animate-pill-fade my-2.5 rounded-xl border p-3.5 shadow-sm transition-colors ${
        approval.status === "pending"
          ? "border-solar-orange/60 bg-solar-yellow/10"
          : approval.status === "approved"
          ? "border-bea-emerald/50 bg-bea-emerald/10"
          : "border-solar-red/40 bg-bea-coral/20"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-neutral-800">
          {isCommand ? (
            <Terminal className="h-4 w-4 text-solar-red-orange" />
          ) : (
            <FileEdit className="h-4 w-4 text-solar-red-orange" />
          )}
          <span>
            Approval Required:{" "}
            <code className="rounded bg-bea-card px-1.5 py-0.5 text-bea-burgundy">
              {approval.tool_name}
            </code>
          </span>
        </div>
        <span
          className={`select-none rounded px-2 py-0.5 text-[10px] font-bold tracking-wide ${
            approval.status === "pending"
              ? "bg-solar-orange/20 text-bea-burgundy"
              : approval.status === "approved"
              ? "bg-bea-emerald/20 text-bea-teal"
              : "bg-solar-red/15 text-solar-red"
          }`}
        >
          {approval.status.toUpperCase()}
        </span>
      </div>

      {cmdLine && (
        <div className="mt-2 rounded-lg border border-bea-border bg-bea-card px-3 py-2 font-mono text-xs text-bea-teal">
          $ {cmdLine}
        </div>
      )}

      {targetFile && (
        <div className="mt-2 text-xs text-bea-text-primary">
          Target:{" "}
          <code className="rounded bg-bea-card px-1.5 py-0.5 text-bea-blue">
            {targetFile}
          </code>
        </div>
      )}

      <details className="mt-2">
        <summary className="cursor-pointer text-[11px] font-medium text-bea-text-secondary hover:text-neutral-800">
          Inspect full tool arguments
        </summary>
        <pre className="mt-1.5 max-h-48 overflow-auto rounded-lg border border-bea-border bg-bea-card p-2.5 text-[11px] text-bea-text-primary">
          {JSON.stringify(approval.args, null, 2)}
        </pre>
      </details>

      {approval.status === "pending" ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={submitting}
            onClick={() => handleClick(true)}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-bea-emerald px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Check className="h-3.5 w-3.5" />
            Approve
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={() => handleClick(false)}
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-solar-red/40 bg-bea-card px-3 py-1.5 text-xs font-semibold text-solar-red transition hover:bg-bea-coral/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-3.5 w-3.5" />
            Deny
          </button>
          <span className="ml-auto flex items-center gap-1 text-[11px] text-bea-text-secondary">
            <ShieldAlert className="h-3.5 w-3.5 text-solar-orange" />
            Ask-Before-Fix policy paused execution
          </span>
        </div>
      ) : null}
    </div>
  );
}
