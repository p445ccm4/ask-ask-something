"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AgentWorkbench,
  AuthLoginModal,
  useAgentWorkbench,
  type ToolSummarizer,
} from "@ag-workbench/index";
import { DeployModal } from "@/components/DeployModal";
import { GitDiffPanel } from "@/components/GitDiffPanel";
import { HeaderBar } from "@/components/HeaderBar";
import { UatDashboard } from "@/components/UatDashboard";
import type {
  TargetEnv,
  UatOverview,
  WorkspaceGitInfo,
  WorkspaceSummary,
} from "@/lib/types";

const ASK_QUICK_PROMPTS = [
  "Summarize the current UAT pass/fail status and main failure patterns.",
  "Inspect the system prompt and RAG retrieval code in this repository.",
  "Show the current uncommitted git diff for this service.",
];

const askToolSummarizer: ToolSummarizer = (name, args) => {
  if (name === "get_uat_case_detail") {
    const caseId = typeof args?.case_id === "string" ? args.case_id.trim() : "";
    return {
      summary: caseId ? `Case ${caseId}` : "",
      consumedKeys: ["case_id"],
    };
  }
  if (name === "run_uat_check") {
    const caseIds = typeof args?.case_ids === "string" ? args.case_ids.trim() : "";
    const runs = typeof args?.runs === "number" ? args.runs : undefined;
    const base = caseIds ? `Cases: ${caseIds}` : "Full UAT suite";
    return {
      summary: runs && runs > 1 ? `${base} (${runs}x)` : base,
      consumedKeys: ["case_ids", "runs"],
    };
  }
  if (name === "get_uat_summary") {
    return { summary: "Workspace UAT overview" };
  }
  if (name === "get_git_diff") {
    return { summary: "Scoped git diff" };
  }
  return null;
};

export default function WorkbenchPage() {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWsId, setActiveWsId] = useState<string>("");
  const activeWsIdRef = useRef<string>("");
  activeWsIdRef.current = activeWsId;

  const [overview, setOverview] = useState<UatOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);

  const [gitInfo, setGitInfo] = useState<WorkspaceGitInfo | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  const [gitDrawerOpen, setGitDrawerOpen] = useState(false);

  const [deployModalOpen, setDeployModalOpen] = useState(false);
  const [deployTargetEnv, setDeployTargetEnv] = useState<TargetEnv>("dev");

  const [uatRunning, setUatRunning] = useState(false);
  const [uatLogs, setUatLogs] = useState<string[]>([]);

  const [mobileTab, setMobileTab] = useState<"uat" | "agent">("uat");

  const loadWorkspaces = useCallback(async (preferredId?: string) => {
    const res = await fetch("/api/workspaces");
    if (!res.ok) return;
    const data = await res.json();
    const list: WorkspaceSummary[] = data.workspaces || [];
    setWorkspaces(list);
    if (list.length > 0) {
      setActiveWsId((curr) => {
        if (preferredId && list.some((w) => w.id === preferredId)) return preferredId;
        if (curr && list.some((w) => w.id === curr)) return curr;
        return list[0].id;
      });
    }
  }, []);

  const loadOverview = useCallback(async (wsId: string) => {
    if (!wsId) return;
    setOverviewLoading(true);
    try {
      const res = await fetch(`/api/workspaces/${encodeURIComponent(wsId)}/uat/overview`);
      if (res.ok) {
        setOverview(await res.json());
      }
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const loadGitDiff = useCallback(async (wsId: string) => {
    if (!wsId) return;
    setGitLoading(true);
    try {
      const res = await fetch(`/api/workspaces/${encodeURIComponent(wsId)}/git-diff`);
      if (res.ok) {
        setGitInfo(await res.json());
      }
    } finally {
      setGitLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    if (!activeWsId) return;
    void loadOverview(activeWsId);
    void loadGitDiff(activeWsId);
    setUatLogs([]);
  }, [activeWsId, loadOverview, loadGitDiff]);

  const activeWs = workspaces.find((w) => w.id === activeWsId);

  const wb = useAgentWorkbench({
    workspaceId: activeWsId,
    workspaceName: activeWs?.name,
    apiBase: "/api/workbench",
    initialMode: "read_only",
    onEvent: (ev) => {
      if (ev.type === "git_diff_updated") {
        const evWsId = typeof ev.workspace_id === "string" ? ev.workspace_id : "";
        const currentWsId = activeWsIdRef.current;
        if (ev.git && (!evWsId || evWsId === currentWsId)) {
          setGitInfo(ev.git as WorkspaceGitInfo);
        }
        const targetWsId = currentWsId || evWsId;
        if (targetWsId) {
          void loadWorkspaces(targetWsId);
        }
      }
    },
    onTurnDone: () => {
      const wsId = activeWsIdRef.current;
      if (!wsId) return;
      void loadWorkspaces(wsId);
      void loadGitDiff(wsId);
      void loadOverview(wsId);
    },
    notifications: {
      appId: "ask-ask-something",
      appName: "AskAsk* Workbench",
    },
  });

  const handleAddWorkspace = async (payload: {
    name: string;
    path: string;
    uat_path?: string;
  }) => {
    const res = await fetch("/api/workspaces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to add repository");
    await loadWorkspaces(data.workspace?.id);
  };

  const handleStartUatRun = async (req: {
    case_ids?: string;
    turn?: number;
    runs?: number;
  }) => {
    if (!activeWsId) return;
    setUatRunning(true);
    setUatLogs(["Starting UAT batch runner..."]);
    try {
      const res = await fetch(
        `/api/workspaces/${encodeURIComponent(activeWsId)}/uat/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(req),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        const errDetail = data.detail || "Failed to start UAT";
        setUatLogs((prev) => [...prev, `ERROR: ${errDetail}`]);
        wb.notify({
          title: "UAT run failed to start",
          body: `${workspaces.find((w) => w.id === activeWsId)?.name || activeWsId} · ${errDetail}`,
          tag: `uat:${activeWsId}`,
          onClick: () => setMobileTab("uat"),
        });
        setUatRunning(false);
        return;
      }

      const streamRes = await fetch(
        `/api/uat/jobs/${encodeURIComponent(data.job_id)}/stream`
      );
      if (!streamRes.body) {
        setUatRunning(false);
        return;
      }
      const reader = streamRes.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          try {
            const ev = JSON.parse(line.slice(5).trim());
            if (ev.type === "log") {
              setUatLogs((prev) => [...prev, ev.line]);
            } else if (ev.type === "done") {
              setUatLogs((prev) => [
                ...prev,
                `Finished (${ev.status}, exit=${ev.exit_code}).`,
              ]);
              const wsLabel =
                workspaces.find((w) => w.id === activeWsId)?.name || activeWsId;
              wb.notify({
                title: ev.exit_code === 0 ? "UAT run passed" : "UAT run finished",
                body: `${wsLabel} · ${ev.status} (exit=${ev.exit_code})`,
                tag: `uat:${activeWsId}`,
                onClick: () => setMobileTab("uat"),
              });
              await loadOverview(activeWsId);
            }
          } catch {
            // ignore malformed frame
          }
        }
      }
    } finally {
      setUatRunning(false);
    }
  };

  const handleDiagnoseCase = (prompt: string, shouldFix: boolean) => {
    let nextMode = wb.mode;
    if (shouldFix && wb.mode === "read_only") {
      nextMode = "ask_before_fix";
      wb.setMode("ask_before_fix");
    } else if (!shouldFix && wb.mode !== "read_only") {
      nextMode = "read_only";
      wb.setMode("read_only");
    }
    setMobileTab("agent");
    void wb.sendMessage(prompt, nextMode);
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bea-canvas text-bea-text-primary">
      <HeaderBar
        workspaces={workspaces}
        activeWorkspaceId={activeWsId}
        onSelectWorkspace={setActiveWsId}
        onAddWorkspace={handleAddWorkspace}
        onOpenGitDiff={() => {
          if (activeWsId) void loadGitDiff(activeWsId);
          setGitDrawerOpen(true);
        }}
        onOpenDeploy={(env) => {
          setDeployTargetEnv(env);
          setDeployModalOpen(true);
        }}
      />

      {/* Mobile Tab Switcher */}
      <div className="flex border-b border-bea-border bg-bea-card lg:hidden">
        <button
          type="button"
          onClick={() => setMobileTab("uat")}
          className={`flex-1 py-2 text-xs font-semibold ${
            mobileTab === "uat"
              ? "border-b-2 border-solar-red text-solar-red"
              : "text-bea-text-secondary"
          }`}
        >
          UAT Dashboard
        </button>
        <button
          type="button"
          onClick={() => setMobileTab("agent")}
          className={`flex-1 py-2 text-xs font-semibold ${
            mobileTab === "agent"
              ? "border-b-2 border-solar-red text-solar-red"
              : "text-bea-text-secondary"
          }`}
        >
          Antigravity Agent
        </button>
      </div>

      {/* Main Split Workspace */}
      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-bea-border">
        <div
          className={`min-h-0 flex-col ${
            mobileTab === "uat" ? "flex" : "hidden lg:flex"
          }`}
        >
          <UatDashboard
            workspaceId={activeWsId}
            overview={overview}
            loading={overviewLoading}
            runningLogs={uatLogs}
            isUatRunning={uatRunning}
            onRefresh={() => loadOverview(activeWsId)}
            onStartRun={handleStartUatRun}
            onDiagnoseCase={handleDiagnoseCase}
          />
        </div>

        <div
          className={`min-h-0 flex-col ${
            mobileTab === "agent" ? "flex" : "hidden lg:flex"
          }`}
        >
          <AgentWorkbench
            workspaceId={activeWsId}
            workspaceName={activeWs?.name || "Workspace"}
            apiBase="/api/workbench"
            mode={wb.mode}
            onChangeMode={wb.setMode}
            sandboxStatus={wb.health?.sandbox_status}
            availableModels={wb.availableModels}
            selectedModel={wb.selectedModel}
            onSelectModel={wb.setSelectedModel}
            slashCommands={wb.slashCommands}
            onSearchFiles={wb.searchWorkspaceFiles}
            conversations={wb.conversations}
            totalConversations={wb.totalConversations}
            hasMoreConversations={wb.hasMoreConversations}
            activeConversationId={wb.activeConvId}
            sessionStates={wb.sessionStates}
            messages={wb.messages}
            streaming={wb.streaming}
            onSelectConversation={wb.selectConversation}
            onNewConversation={() => {
              if (activeWsId) void wb.createConversation(activeWsId);
            }}
            onCloseConversation={wb.closeConversation}
            onSearchConversations={wb.searchConversations}
            onRenameConversation={wb.renameConversation}
            onSendMessage={(txt, files) => wb.sendMessage(txt, undefined, files)}
            onStopStreaming={wb.stopStreaming}
            onDecideApproval={wb.decideApproval}
            emptyTitle={`Maintainer ready for ${activeWs?.name || "Workspace"}`}
            emptyDescription="Inspect code, analyze failing UAT turns, apply sandboxed fixes, and verify regressions."
            quickPrompts={ASK_QUICK_PROMPTS}
            toolSummarizer={askToolSummarizer}
            notifications={wb.notifications}
          />
        </div>
      </main>

      <GitDiffPanel
        open={gitDrawerOpen}
        onClose={() => setGitDrawerOpen(false)}
        workspaceName={activeWs?.name || ""}
        hasUatTarget={Boolean(activeWs && (activeWs.uat_exists || activeWs.env === "uat"))}
        gitInfo={gitInfo}
        loading={gitLoading}
        onRefresh={() => loadGitDiff(activeWsId)}
        onOpenDeploy={(env) => {
          setDeployTargetEnv(env);
          setDeployModalOpen(true);
        }}
      />

      <DeployModal
        open={deployModalOpen}
        workspaceId={activeWsId}
        workspaceName={activeWs?.name || ""}
        targetEnv={deployTargetEnv}
        onClose={() => setDeployModalOpen(false)}
        onDeployed={() => {
          void loadWorkspaces(activeWsId);
          void loadGitDiff(activeWsId);
        }}
      />

      <AuthLoginModal
        apiBase="/api/workbench"
        authStatus={wb.authStatus}
        errorMessage={wb.authErrorMessage}
        onAuthenticated={() => {
          void wb.recheckAuthStatus(true);
        }}
        onRecheck={() => wb.recheckAuthStatus(true)}
      />
    </div>
  );
}
