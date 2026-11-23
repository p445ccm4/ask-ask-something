"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AgentWorkbench, type ToolSummarizer } from "@ag-workbench/index";
import { DeployModal } from "@/components/DeployModal";
import { GitDiffPanel } from "@/components/GitDiffPanel";
import { HeaderBar } from "@/components/HeaderBar";
import { UatDashboard } from "@/components/UatDashboard";
import type {
  ChatMessage,
  ConversationRecord,
  ExecutionMode,
  HealthStatus,
  ModelOption,
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

const DEFAULT_MODEL_OPTIONS: ModelOption[] = [
  { id: "", label: "Auto (gemini-4-hydrogen)" },
  { id: "gemini-4-hydrogen", label: "Gemini 4 Hydrogen" },
  { id: "gemini-4-argon", label: "Gemini 4 Argon" },
  { id: "gemini-3.8-flash", label: "Gemini 3.8 Flash" },
  { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
  { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
];

export default function WorkbenchPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWsId, setActiveWsId] = useState<string>("");
  const [mode, setMode] = useState<ExecutionMode>("read_only");
  const [selectedModel, setSelectedModel] = useState<string>("");

  const [overview, setOverview] = useState<UatOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);

  const [gitInfo, setGitInfo] = useState<WorkspaceGitInfo | null>(null);
  const [gitLoading, setGitLoading] = useState(false);
  const [gitDrawerOpen, setGitDrawerOpen] = useState(false);

  const [deployModalOpen, setDeployModalOpen] = useState(false);
  const [deployTargetEnv, setDeployTargetEnv] = useState<TargetEnv>("dev");

  const [uatRunning, setUatRunning] = useState(false);
  const [uatLogs, setUatLogs] = useState<string[]>([]);

  const [conversations, setConversations] = useState<ConversationRecord[]>([]);
  const [activeConvId, setActiveConvId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatStreaming, setChatStreaming] = useState(false);
  const chatAbortRef = useRef<AbortController | null>(null);
  const userCancelledRef = useRef(false);

  const [mobileTab, setMobileTab] = useState<"uat" | "agent">("uat");

  const availableModels =
    health?.available_models && health.available_models.length > 0
      ? health.available_models
      : DEFAULT_MODEL_OPTIONS;

  const loadWorkspaces = useCallback(async (preferredId?: string) => {
    const res = await fetch("/api/workspaces");
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

  const createConversation = useCallback(async (wsId: string, title = "New Investigation") => {
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: wsId, title }),
    });
    const data = await res.json();
    const conv = data.conversation as ConversationRecord;
    setConversations((prev) => [conv, ...prev]);
    setActiveConvId(conv.conversation_id);
    setMessages(conv.messages || []);
    return conv.conversation_id;
  }, []);

  const loadConversations = useCallback(
    async (wsId: string) => {
      if (!wsId) return;
      const res = await fetch(
        `/api/conversations?workspace_id=${encodeURIComponent(wsId)}`
      );
      const data = await res.json();
      const list: ConversationRecord[] = data.conversations || [];
      setConversations(list);
      if (list.length > 0) {
        setActiveConvId(list[0].conversation_id);
        setMessages(list[0].messages || []);
      } else {
        await createConversation(wsId);
      }
    },
    [createConversation]
  );

  useEffect(() => {
    fetch("/api/health?check_sandbox=true")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: HealthStatus | null) => {
        if (!d) return;
        setHealth(d);
        if (d.default_model) {
          setSelectedModel(d.default_model);
        }
      })
      .catch(() => {});
    loadWorkspaces();
  }, [loadWorkspaces]);

  useEffect(() => {
    if (!activeWsId) return;
    loadOverview(activeWsId);
    loadGitDiff(activeWsId);
    loadConversations(activeWsId);
    setUatLogs([]);
  }, [activeWsId, loadOverview, loadGitDiff, loadConversations]);

  const handleSelectConversation = async (convId: string) => {
    setActiveConvId(convId);
    const res = await fetch(`/api/conversations/${encodeURIComponent(convId)}`);
    if (res.ok) {
      const data = await res.json();
      setMessages(data.conversation?.messages || []);
    }
  };

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
        setUatLogs((prev) => [...prev, `ERROR: ${data.detail || "Failed to start UAT"}`]);
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

  const sendChatMessage = async (
    text: string,
    overrideMode?: ExecutionMode
  ) => {
    if (!activeWsId || chatStreaming) return;
    const effectiveMode = overrideMode || mode;
    let convId = activeConvId;
    if (!convId) {
      convId = await createConversation(activeWsId);
    }

    setMobileTab("agent");
    setChatStreaming(true);

    const activeModelLabel =
      availableModels.find((m) => m.id === selectedModel)?.label ||
      selectedModel ||
      undefined;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      {
        role: "assistant",
        content: "",
        thought: "",
        tool_events: [],
        approvals: [],
        mode: effectiveMode,
        model: activeModelLabel,
        streaming: true,
      },
    ]);

    const updateLastAssistant = (updater: (msg: ChatMessage) => ChatMessage) => {
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const copy = [...prev];
        const lastIdx = copy.length - 1;
        if (copy[lastIdx].role === "assistant") {
          copy[lastIdx] = updater(copy[lastIdx]);
        }
        return copy;
      });
    };

    const controller = new AbortController();
    chatAbortRef.current = controller;
    userCancelledRef.current = false;

    try {
      const res = await fetch(
        `/api/conversations/${encodeURIComponent(convId)}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            workspace_id: activeWsId,
            message: text,
            mode: effectiveMode,
            model: selectedModel || undefined,
          }),
        }
      );

      if (!res.ok || !res.body) {
        const errText = await res.text();
        updateLastAssistant((m) => ({
          ...m,
          streaming: false,
          error: errText || `HTTP ${res.status}`,
        }));
        return;
      }

      const reader = res.body.getReader();
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
          let ev: Record<string, unknown>;
          try {
            ev = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }

          const evType = String(ev.type || "");
          if (evType === "thought") {
            updateLastAssistant((m) => ({
              ...m,
              thought: (m.thought || "") + String(ev.delta || ""),
            }));
          } else if (evType === "text") {
            updateLastAssistant((m) => ({
              ...m,
              content: (m.content || "") + String(ev.delta || ""),
            }));
          } else if (evType === "tool_call" || evType === "tool_result") {
            updateLastAssistant((m) => ({
              ...m,
              tool_events: [
                ...(m.tool_events || []),
                {
                  type: evType as "tool_call" | "tool_result",
                  id: ev.id as string | undefined,
                  name: String(ev.name || ""),
                  args: ev.args as Record<string, unknown> | undefined,
                  result: ev.result as string | undefined,
                  error: ev.error as string | null | undefined,
                },
              ],
            }));
          } else if (evType === "approval_required") {
            updateLastAssistant((m) => ({
              ...m,
              approvals: [
                ...(m.approvals || []),
                {
                  approval_id: String(ev.approval_id || ""),
                  conversation_id: String(ev.conversation_id || convId),
                  tool_name: String(ev.tool_name || ""),
                  args: (ev.args as Record<string, unknown>) || {},
                  status: "pending",
                },
              ],
            }));
          } else if (evType === "approval_resolved") {
            const aid = String(ev.approval_id || "");
            const approved = Boolean(ev.approved);
            updateLastAssistant((m) => ({
              ...m,
              approvals: (m.approvals || []).map((a) =>
                a.approval_id === aid
                  ? { ...a, status: approved ? "approved" : "denied" }
                  : a
              ),
            }));
          } else if (evType === "git_diff_updated") {
            if (ev.git) setGitInfo(ev.git as WorkspaceGitInfo);
            loadWorkspaces(activeWsId);
          } else if (evType === "error") {
            updateLastAssistant((m) => ({
              ...m,
              streaming: false,
              error: String(ev.message || "Agent execution error"),
            }));
          } else if (evType === "done") {
            const wasCancelled = Boolean(ev.cancelled);
            updateLastAssistant((m) => ({
              ...m,
              streaming: false,
              cancelled: wasCancelled || m.cancelled,
            }));
            loadWorkspaces(activeWsId);
            loadGitDiff(activeWsId);
            loadOverview(activeWsId);
          }
        }
      }

      updateLastAssistant((m) => ({ ...m, streaming: false }));
    } catch (err) {
      const isAbort =
        userCancelledRef.current ||
        (err instanceof DOMException && err.name === "AbortError");
      if (isAbort) {
        updateLastAssistant((m) => ({
          ...m,
          streaming: false,
          cancelled: true,
        }));
      } else {
        updateLastAssistant((m) => ({
          ...m,
          streaming: false,
          error: err instanceof Error ? err.message : String(err),
        }));
      }
    } finally {
      chatAbortRef.current = null;
      setChatStreaming(false);
    }
  };

  const handleStopChat = async () => {
    if (!chatStreaming) return;
    userCancelledRef.current = true;
    chatAbortRef.current?.abort();
    const convId = activeConvId;
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const copy = [...prev];
      const lastIdx = copy.length - 1;
      if (copy[lastIdx].role === "assistant") {
        copy[lastIdx] = {
          ...copy[lastIdx],
          streaming: false,
          cancelled: true,
          approvals: (copy[lastIdx].approvals || []).map((a) =>
            a.status === "pending" ? { ...a, status: "denied" } : a
          ),
        };
      }
      return copy;
    });
    if (convId) {
      fetch(`/api/conversations/${encodeURIComponent(convId)}/cancel`, {
        method: "POST",
      }).catch(() => {});
    }
  };

  const handleDiagnoseCase = (prompt: string, shouldFix: boolean) => {
    let nextMode = mode;
    if (shouldFix && mode === "read_only") {
      nextMode = "ask_before_fix";
      setMode("ask_before_fix");
    } else if (!shouldFix && mode !== "read_only") {
      nextMode = "read_only";
      setMode("read_only");
    }
    sendChatMessage(prompt, nextMode);
  };

  const handleDecideApproval = async (approvalId: string, approved: boolean) => {
    const res = await fetch(
      `/api/approvals/${encodeURIComponent(approvalId)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      }
    );
    if (res.ok) {
      setMessages((prev) =>
        prev.map((m) => ({
          ...m,
          approvals: (m.approvals || []).map((a) =>
            a.approval_id === approvalId
              ? { ...a, status: approved ? "approved" : "denied" }
              : a
          ),
        }))
      );
    }
  };

  const activeWs = workspaces.find((w) => w.id === activeWsId);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bea-canvas text-bea-text-primary">
      <HeaderBar
        workspaces={workspaces}
        activeWorkspaceId={activeWsId}
        onSelectWorkspace={setActiveWsId}
        onAddWorkspace={handleAddWorkspace}
        onOpenGitDiff={() => {
          if (activeWsId) loadGitDiff(activeWsId);
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
            workspaceName={activeWs?.name || "Workspace"}
            mode={mode}
            onChangeMode={setMode}
            sandboxStatus={health?.sandbox_status}
            availableModels={availableModels}
            selectedModel={selectedModel}
            onSelectModel={setSelectedModel}
            conversations={conversations}
            activeConversationId={activeConvId}
            messages={messages}
            streaming={chatStreaming}
            onSelectConversation={handleSelectConversation}
            onNewConversation={() => createConversation(activeWsId)}
            onSendMessage={(txt) => sendChatMessage(txt)}
            onStopStreaming={handleStopChat}
            onDecideApproval={handleDecideApproval}
            emptyTitle={`Maintainer ready for ${activeWs?.name || "Workspace"}`}
            emptyDescription="Inspect code, analyze failing UAT turns, apply sandboxed fixes, and verify regressions."
            quickPrompts={ASK_QUICK_PROMPTS}
            toolSummarizer={askToolSummarizer}
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
          loadWorkspaces(activeWsId);
          loadGitDiff(activeWsId);
        }}
      />
    </div>
  );
}
