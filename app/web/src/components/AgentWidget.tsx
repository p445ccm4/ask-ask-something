"use client";

import React, { useEffect, useMemo } from "react";
import { Bot, Maximize2, Minimize2, Minus } from "lucide-react";
import {
  AgentWorkbench,
  deriveBrowserIconStatus,
  type AgentWorkbenchProps,
  type BrowserIconStatus,
  type ConversationSummary,
  type SessionRuntimeState,
} from "@ag-workbench/index";
import type { EnvName, ProjectSummary } from "@/lib/types";

export type WidgetMode = "minimized" | "compact" | "expanded";

interface AgentWidgetProps {
  project: ProjectSummary | null;
  activeEnv: EnvName;
  widgetMode: WidgetMode;
  onChangeWidgetMode: (mode: WidgetMode) => void;
  conversations: ConversationSummary[];
  activeConversationId: string;
  sessionStates: Record<string, SessionRuntimeState>;
  onClearUnread: () => void;
  workbenchProps: Omit<
    AgentWorkbenchProps,
    "isChatVisible" | "onClearUnread" | "workspaceId" | "workspaceName"
  >;
}

const DOT_COLOR_CLASS: Record<BrowserIconStatus, string> = {
  idle: "bg-bea-emerald",
  running: "bg-solar-orange animate-pulse",
  unread: "bg-solar-red",
  failed: "bg-bea-burgundy",
};

const STATUS_LABEL: Record<BrowserIconStatus, string> = {
  idle: "Ready",
  running: "Running...",
  unread: "New",
  failed: "Error",
};

export function AgentWidget({
  project,
  activeEnv,
  widgetMode,
  onChangeWidgetMode,
  conversations,
  activeConversationId,
  sessionStates,
  onClearUnread,
  workbenchProps,
}: AgentWidgetProps) {
  const isOpen = widgetMode !== "minimized";

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        if (widgetMode === "minimized") {
          onChangeWidgetMode("compact");
          onClearUnread();
        } else {
          onChangeWidgetMode("minimized");
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [widgetMode, onChangeWidgetMode, onClearUnread]);

  const iconStatus = useMemo<BrowserIconStatus>(() => {
    return deriveBrowserIconStatus({
      activeConversationId,
      openTabIds: conversations.map((c) => c.conversation_id),
      sessionStates,
      streaming: workbenchProps.streaming,
    });
  }, [conversations, activeConversationId, sessionStates, workbenchProps.streaming]);

  const envCount = project?.configured_envs.length ?? 0;
  const projectName = project?.name || "Project";

  return (
    <div className="fixed right-5 bottom-5 z-40 flex flex-col items-end">
      {/* Minimized Launcher Pill */}
      {!isOpen && (
        <button
          type="button"
          onClick={() => {
            onChangeWidgetMode("compact");
            onClearUnread();
          }}
          title="Open AGY Agent (Ctrl/Cmd + J)"
          className="inline-flex cursor-pointer items-center gap-2.5 rounded-full border border-bea-border bg-bea-card px-4 py-2.5 text-xs font-bold text-bea-text-strong shadow-xl transition hover:-translate-y-0.5 hover:border-solar-red"
        >
          <span className={`h-2.5 w-2.5 rounded-full ${DOT_COLOR_CLASS[iconStatus]}`} />
          <Bot className="h-4 w-4 text-solar-red" />
          <span>AGY Agent</span>
          <span className="font-mono text-[11px] font-medium text-bea-text-secondary">
            {projectName} · {envCount} {envCount === 1 ? "repo" : "repos"}
          </span>
          {iconStatus === "unread" && (
            <span className="rounded-full bg-solar-red px-2 py-0.5 text-[10px] font-extrabold text-white">
              New
            </span>
          )}
          {iconStatus === "running" && (
            <span className="rounded-full bg-solar-orange/20 px-2 py-0.5 text-[10px] font-extrabold text-solar-red-orange">
              Running
            </span>
          )}
          {iconStatus === "failed" && (
            <span className="rounded-full bg-bea-coral/35 px-2 py-0.5 text-[10px] font-extrabold text-bea-burgundy">
              Error
            </span>
          )}
          <kbd className="hidden rounded border border-bea-border bg-bea-canvas px-1.5 py-0.5 font-mono text-[10px] text-bea-text-secondary sm:inline">
            ⌘J
          </kbd>
        </button>
      )}

      {/* Always-mounted AgentWorkbench container (hidden via CSS when minimized so drafts/scroll/single icon controller stay alive) */}
      <div
        className={`flex flex-col overflow-hidden rounded-2xl border border-bea-border bg-bea-card shadow-2xl transition-all ${
          !isOpen
            ? "hidden"
            : widgetMode === "expanded"
            ? "h-[84vh] w-[min(760px,calc(100vw-2rem))]"
            : "h-[min(580px,calc(100vh-2.5rem))] w-[min(450px,calc(100vw-2rem))]"
        }`}
      >
        {/* Top Widget Chrome */}
        <div className="flex items-center justify-between gap-2 border-b border-bea-border bg-bea-surface-subtle px-3.5 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT_COLOR_CLASS[iconStatus]}`}
              title={`Agent status: ${STATUS_LABEL[iconStatus]}`}
            />
            <span className="truncate text-xs font-extrabold text-bea-text-strong">
              AGY Agent · {projectName}
            </span>
            <span className="hidden rounded border border-bea-border bg-bea-card px-1.5 py-0.5 font-mono text-[10px] font-semibold text-bea-text-secondary sm:inline">
              {envCount} {envCount === 1 ? "repo" : "repos"} · viewing {activeEnv.toUpperCase()}
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() =>
                onChangeWidgetMode(
                  widgetMode === "expanded" ? "compact" : "expanded"
                )
              }
              title={
                widgetMode === "expanded"
                  ? "Compact size"
                  : "Expand drawer size"
              }
              className="rounded-lg border border-bea-border bg-bea-card p-1.5 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
            >
              {widgetMode === "expanded" ? (
                <Minimize2 className="h-3.5 w-3.5" />
              ) : (
                <Maximize2 className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={() => onChangeWidgetMode("minimized")}
              title="Minimize widget (Ctrl/Cmd + J)"
              className="rounded-lg border border-bea-border bg-bea-card p-1.5 text-bea-text-secondary hover:bg-bea-canvas hover:text-bea-text-strong"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Embedded Antigravity Workbench */}
        <div className="min-h-0 flex-1 overflow-hidden">
          <AgentWorkbench
            {...workbenchProps}
            workspaceId={project?.id || ""}
            workspaceName={projectName}
            isChatVisible={isOpen}
            onClearUnread={onClearUnread}
          />
        </div>
      </div>
    </div>
  );
}
