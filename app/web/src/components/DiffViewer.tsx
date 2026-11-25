"use client";

import React from "react";

interface DiffViewerProps {
  diff: string;
  emptyMessage?: string;
  maxHeightClass?: string;
}

export function DiffViewer({
  diff,
  emptyMessage = "No uncommitted code changes in this service directory.",
  maxHeightClass = "max-h-[420px]",
}: DiffViewerProps) {
  if (!diff.trim()) {
    return (
      <div className="rounded-xl border border-bea-border bg-bea-canvas/70 p-4 text-xs text-bea-text-secondary">
        {emptyMessage}
      </div>
    );
  }

  const lines = diff.split("\n");

  return (
    <div
      className={`overflow-auto rounded-xl border border-bea-border bg-bea-card font-mono text-xs leading-5 ${maxHeightClass}`}
    >
      {lines.map((line, idx) => {
        let cls = "text-bea-text-primary";
        if (line.startsWith("diff --git") || line.startsWith("index ")) {
          cls = "bg-bea-canvas text-bea-text-strong font-semibold";
        } else if (line.startsWith("@@")) {
          cls = "bg-bea-blue/10 text-bea-blue font-medium";
        } else if (line.startsWith("+++") || line.startsWith("---")) {
          cls = "text-bea-text-secondary font-medium";
        } else if (line.startsWith("+")) {
          cls = "bg-bea-emerald/15 text-bea-teal";
        } else if (line.startsWith("-")) {
          cls = "bg-bea-coral/25 text-bea-burgundy";
        }
        return (
          <div key={idx} className={`whitespace-pre px-3 py-0.5 ${cls}`}>
            {line || " "}
          </div>
        );
      })}
    </div>
  );
}
