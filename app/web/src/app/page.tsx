"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AuthLoginModal, useAgentWorkbench, type ToolSummarizer, type WorkbenchTheme } from "@ag-workbench/index";
import { AgentWidget, type WidgetMode } from "@/components/AgentWidget";
import { DeployModal } from "@/components/DeployModal";
import { EvalDashboard } from "@/components/EvalDashboard";
import { GitDiffPanel } from "@/components/GitDiffPanel";
import { HeaderBar } from "@/components/HeaderBar";
import { ImportXlsxModal } from "@/components/ImportXlsxModal";
import { ProjectModal } from "@/components/ProjectModal";
import { SuiteModal } from "@/components/SuiteModal";
import { apiUrl } from "@/lib/basePath";
import type {
  EnvName,
  EvalOverview,
  ProjectSummary,
  TargetEnv,
  WorkspaceGitInfo,
} from "@/lib/types";

const WORKBENCH_API_BASE = apiUrl("/api/workbench");

const askToolSummarizer: ToolSummarizer = (name, args) => {
  const envTag =
    typeof args?.env === "string" && args.env.trim()
      ? args.env.trim().toUpperCase()
      : "";
  const prefix = envTag ? `[${envTag}] ` : "";

  if (name === "list_eval_suites") {
    return {
      summary: `${prefix}List Eval suites`,
      consumedKeys: ["env", "search", "limit", "offset"],
    };
  }
  if (name === "get_eval_summary") {
    return {
      summary: `${prefix}Eval suite summary`,
      consumedKeys: ["env", "suite_id"],
    };
  }
  if (name === "query_eval_cases") {
    const status = typeof args?.status === "string" ? args.status : "ALL";
    return {
      summary: `${prefix}Query Eval cases (${status})`,
      consumedKeys: ["env", "suite_id", "status"],
    };
  }
  if (name === "get_eval_case_detail") {
    const caseId = typeof args?.case_id === "string" ? args.case_id.trim() : "";
    return {
      summary: caseId ? `${prefix}Case ${caseId}` : `${prefix}Case detail`,
      consumedKeys: ["case_id", "env", "suite_id"],
    };
  }
  if (name === "run_eval_check") {
    const caseIds = typeof args?.case_ids === "string" ? args.case_ids.trim() : "";
    const runs = typeof args?.runs === "number" ? args.runs : undefined;
    const base = caseIds ? `Cases: ${caseIds}` : "Full Eval suite";
    const prefixed = envTag ? `${envTag}: ${base}` : base;
    return {
      summary: runs && runs > 1 ? `${prefixed} (${runs}x)` : prefixed,
      consumedKeys: ["case_ids", "runs", "env", "suite_id"],
    };
  }
  if (name === "create_or_update_eval_suite") {
    const suiteName = typeof args?.name === "string" ? args.name.trim() : "";
    return {
      summary: suiteName ? `${prefix}Save suite '${suiteName}'` : `${prefix}Save Eval suite`,
      consumedKeys: ["env", "suite_id", "name"],
    };
  }
  if (name === "upsert_eval_cases") {
    const count = Array.isArray(args?.cases) ? args.cases.length : undefined;
    return {
      summary:
        typeof count === "number"
          ? `${prefix}Upsert ${count} Eval case(s)`
          : `${prefix}Upsert Eval cases`,
      consumedKeys: ["env", "suite_id"],
    };
  }
  if (name === "import_xlsx_suite") {
    const fn = typeof args?.xlsx_path === "string" ? args.xlsx_path.split("/").pop() : "";
    return {
      summary: fn ? `${prefix}Import ${fn}` : `${prefix}Import .xlsx suite`,
      consumedKeys: ["env", "xlsx_path"],
    };
  }
  if (name === "get_git_diff") {
    return {
      summary: envTag ? `Git diff (${envTag})` : "Scoped git diff",
      consumedKeys: ["env"],
    };
  }
  if (name === "compare_envs") {
    const src = typeof args?.source_env === "string" ? args.source_env.toUpperCase() : "";
    const dst = typeof args?.target_env === "string" ? args.target_env.toUpperCase() : "";
    return {
      summary: src && dst ? `${src} vs ${dst} diff` : "Compare environments",
      consumedKeys: ["source_env", "target_env"],
    };
  }
  return null;
};

export default function WorkbenchPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string>("");
  const activeProjectIdRef = useRef<string>("");
  activeProjectIdRef.current = activeProjectId;

  const activeProject = useMemo(
    () => projects.find((p) => p.id === activeProjectId) || null,
    [projects, activeProjectId]
  );

  const [activeEnv, setActiveEnv] = useState<EnvName>("dev");
  const activeEnvRef = useRef<EnvName>("dev");
  activeEnvRef.current = activeEnv;

  const [activeSuiteId, setActiveSuiteId] = useState<string>("");
  const activeSuiteIdRef = useRef<string>("");
  activeSuiteIdRef.current = activeSuiteId;

  const [overview, setOverview] = useState<EvalOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewVersion, setOverviewVersion] = useState(0);

  const [gitInfoByEnv, setGitInfoByEnv] = useState<
    Partial<Record<EnvName, WorkspaceGitInfo>>
  >({});
  const [gitDrawerEnv, setGitDrawerEnv] = useState<EnvName>("dev");
  const [gitLoading, setGitLoading] = useState(false);
  const [gitDrawerOpen, setGitDrawerOpen] = useState(false);

  const [projectModalState, setProjectModalState] = useState<{
    open: boolean;
    mode: "create" | "edit";
  }>({ open: false, mode: "create" });

  const [suiteModalState, setSuiteModalState] = useState<{
    open: boolean;
    mode: "create" | "edit";
    suiteId?: string | null;
  }>({ open: false, mode: "create" });

  const [importXlsxOpen, setImportXlsxOpen] = useState(false);

  const [deployModalOpen, setDeployModalOpen] = useState(false);
  const [deployTargetEnv, setDeployTargetEnv] = useState<TargetEnv>("dev");

  const [evalRunning, setEvalRunning] = useState(false);
  const [evalLogs, setEvalLogs] = useState<string[]>([]);

  const [widgetMode, setWidgetMode] = useState<WidgetMode>("minimized");

  const applyDocumentTheme = useCallback((nextTheme: WorkbenchTheme) => {
    document.documentElement.classList.toggle("dark", nextTheme === "dark");
    document.documentElement.style.colorScheme = nextTheme;
  }, []);

  // Sync browser tab title with Project + Environment
  useEffect(() => {
    if (activeProject) {
      document.title = `AskAsk* — ${activeProject.name} (${activeEnv.toUpperCase()})`;
    } else {
      document.title = "AskAsk* Workbench — Multi-Env Eval & Maintainer";
    }
  }, [activeProject, activeEnv]);

  const loadProjects = useCallback(
    async (preferredId?: string, preferredEnv?: EnvName) => {
      const res = await fetch(apiUrl("/api/projects"));
      if (!res.ok) return;
      const data = await res.json();
      const list: ProjectSummary[] = data.projects || [];
      setProjects(list);
      if (list.length === 0) {
        setActiveProjectId("");
        return;
      }
      const nextProj =
        (preferredId && list.find((p) => p.id === preferredId)) ||
        list.find((p) => p.id === activeProjectIdRef.current) ||
        list[0];
      setActiveProjectId(nextProj.id);
      const chosenEnv: EnvName =
        preferredEnv && nextProj.configured_envs.includes(preferredEnv)
          ? preferredEnv
          : nextProj.configured_envs.includes(nextProj.active_env)
          ? nextProj.active_env
          : nextProj.configured_envs[0] || "dev";
      setActiveEnv(chosenEnv);
    },
    []
  );

  const loadOverview = useCallback(
    async (projId: string, env: EnvName, suiteId?: string) => {
      if (!projId) return;
      setOverviewLoading(true);
      try {
        const params = new URLSearchParams({ env });
        if (suiteId && suiteId.trim()) params.set("suite_id", suiteId.trim());
        const res = await fetch(
          apiUrl(
            `/api/projects/${encodeURIComponent(
              projId
            )}/eval/overview?${params.toString()}`
          )
        );
        if (res.ok) {
          const data = (await res.json()) as EvalOverview;
          setOverview(data);
          setActiveSuiteId(data.active_suite?.id || "");
          setOverviewVersion((v) => v + 1);
        }
      } finally {
        setOverviewLoading(false);
      }
    },
    []
  );

  const loadAllGitDiffs = useCallback(async (proj: ProjectSummary | null) => {
    if (!proj || proj.configured_envs.length === 0) {
      setGitInfoByEnv({});
      return;
    }
    setGitLoading(true);
    try {
      const pairs = await Promise.all(
        proj.configured_envs.map(async (env) => {
          const res = await fetch(
            apiUrl(
              `/api/projects/${encodeURIComponent(proj.id)}/git-diff?env=${env}`
            )
          );
          if (!res.ok) return [env, null] as const;
          return [env, (await res.json()) as WorkspaceGitInfo] as const;
        })
      );
      const nextMap: Partial<Record<EnvName, WorkspaceGitInfo>> = {};
      for (const [env, info] of pairs) {
        if (info) nextMap[env] = info;
      }
      setGitInfoByEnv(nextMap);
    } finally {
      setGitLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!activeProject) return;
    setGitDrawerEnv(activeEnv);
    setEvalLogs([]);
    setActiveSuiteId("");
    void loadOverview(activeProject.id, activeEnv);
    void loadAllGitDiffs(activeProject);
  }, [activeProject?.id, activeEnv]); // eslint-disable-line react-hooks/exhaustive-deps

  const wb = useAgentWorkbench({
    workspaceId: activeProjectId,
    workspaceName: activeProject?.name,
    apiBase: WORKBENCH_API_BASE,
    initialMode: "read_only",
    isChatVisible: widgetMode !== "minimized",
    onEvent: (ev) => {
      if (ev.type === "git_diff_updated") {
        const evProjId =
          typeof ev.workspace_id === "string" ? ev.workspace_id : "";
        const currProjId = activeProjectIdRef.current;
        if (!evProjId || evProjId === currProjId) {
          if (ev.env_git && typeof ev.env_git === "object") {
            setGitInfoByEnv(
              ev.env_git as Partial<Record<EnvName, WorkspaceGitInfo>>
            );
          } else if (ev.git) {
            setGitInfoByEnv((prev) => ({
              ...prev,
              [activeEnvRef.current]: ev.git as WorkspaceGitInfo,
            }));
          }
        }
        const targetId = currProjId || evProjId;
        if (targetId) void loadProjects(targetId, activeEnvRef.current);
      }
    },
    onTurnDone: () => {
      const projId = activeProjectIdRef.current;
      if (!projId) return;
      void loadProjects(projId, activeEnvRef.current);
      void loadOverview(projId, activeEnvRef.current, activeSuiteIdRef.current);
    },
    notifications: {
      appId: "ask-ask-something",
      appName: "AskAsk* Workbench",
    },
  });

  const handleSelectProject = (nextProjId: string) => {
    const proj = projects.find((p) => p.id === nextProjId);
    setActiveProjectId(nextProjId);
    if (proj) {
      const nextEnv = proj.configured_envs.includes(proj.active_env)
        ? proj.active_env
        : proj.configured_envs[0] || "dev";
      setActiveEnv(nextEnv);
    }
  };

  const handleSelectEnv = async (env: EnvName) => {
    setActiveEnv(env);
    if (!activeProjectId) return;
    // Persist active_env on project so agent tools default to this env too
    fetch(apiUrl(`/api/projects/${encodeURIComponent(activeProjectId)}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_env: env }),
    })
      .then(() => loadProjects(activeProjectId, env))
      .catch(() => {});
  };

  const handleSaveProject = async (payload: {
    projectId?: string;
    name: string;
    environments: Partial<Record<EnvName, string>>;
    active_env: EnvName;
  }) => {
    const isEdit = Boolean(payload.projectId);
    const url = isEdit
      ? apiUrl(`/api/projects/${encodeURIComponent(payload.projectId!)}`)
      : apiUrl("/api/projects");
    const res = await fetch(url, {
      method: isEdit ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: payload.name,
        environments: payload.environments,
        active_env: payload.active_env,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to save project");
    await loadProjects(data.project?.id, data.project?.active_env);
  };

  const handleDeleteProject = async (projectId: string) => {
    const res = await fetch(
      apiUrl(`/api/projects/${encodeURIComponent(projectId)}`),
      { method: "DELETE" }
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to delete project");
    await loadProjects();
  };

  const handleStartEvalRun = async (req: {
    suite_id?: string;
    case_ids?: string;
    turn?: number;
    runs?: number;
  }) => {
    if (!activeProjectId) return;
    const chosenSuiteId = req.suite_id || activeSuiteId;
    setEvalRunning(true);
    setEvalLogs([
      `Starting Eval runner on ${activeProject?.name || activeProjectId} (${activeEnv.toUpperCase()})...`,
    ]);
    try {
      const res = await fetch(
        apiUrl(`/api/projects/${encodeURIComponent(activeProjectId)}/eval/run`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            env: activeEnv,
            suite_id: chosenSuiteId || undefined,
            case_ids: req.case_ids || "",
            turn: req.turn,
            runs: req.runs ?? 1,
          }),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        const errDetail = data.detail || "Failed to start Eval run";
        setEvalLogs((prev) => [...prev, `ERROR: ${errDetail}`]);
        wb.notify({
          title: "Eval run failed to start",
          body: `${activeProject?.name || activeProjectId} (${activeEnv.toUpperCase()}) · ${errDetail}`,
          tag: `eval:${activeProjectId}:${activeEnv}`,
        });
        setEvalRunning(false);
        return;
      }

      const streamRes = await fetch(
        apiUrl(`/api/eval/jobs/${encodeURIComponent(data.job_id)}/stream`)
      );
      if (!streamRes.body) {
        setEvalRunning(false);
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
              setEvalLogs((prev) => [...prev, ev.line]);
            } else if (ev.type === "done") {
              setEvalLogs((prev) => [
                ...prev,
                `Finished (${ev.status}, exit=${ev.exit_code}).`,
              ]);
              wb.notify({
                title: ev.exit_code === 0 ? "Eval run passed" : "Eval run finished",
                body: `${activeProject?.name || activeProjectId} (${activeEnv.toUpperCase()}) · ${ev.status} (exit=${ev.exit_code})`,
                tag: `eval:${activeProjectId}:${activeEnv}`,
              });
              await loadOverview(activeProjectId, activeEnv, chosenSuiteId);
              await loadProjects(activeProjectId, activeEnv);
            }
          } catch {
            // ignore malformed frame
          }
        }
      }
    } finally {
      setEvalRunning(false);
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
    if (widgetMode === "minimized") {
      setWidgetMode("compact");
    }
    wb.markActiveSessionRead();
    void wb.sendMessage(prompt, nextMode);
  };

  const quickPrompts = useMemo(() => {
    const pName = activeProject?.name || "this project";
    const envUpper = activeEnv.toUpperCase();
    return [
      `Summarize the Eval pass/fail status for ${pName} (${envUpper}) and main failure patterns.`,
      `Inspect the system prompt and RAG retrieval code in the ${envUpper} repository.`,
      `Compare code changes between environments (e.g. DEV vs UAT) for ${pName}.`,
    ];
  }, [activeProject?.name, activeEnv]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bea-canvas text-bea-text-primary">
      <HeaderBar
        projects={projects}
        activeProjectId={activeProjectId}
        activeEnv={activeEnv}
        activeEndpoint={overview?.active_suite?.endpoint}
        onSelectProject={handleSelectProject}
        onSelectEnv={(env) => void handleSelectEnv(env)}
        onOpenNewProject={() =>
          setProjectModalState({ open: true, mode: "create" })
        }
        onOpenEditProject={() =>
          setProjectModalState({ open: true, mode: "edit" })
        }
        onOpenGitDiff={(env) => {
          setGitDrawerEnv(env || activeEnv);
          if (activeProject) void loadAllGitDiffs(activeProject);
          setGitDrawerOpen(true);
        }}
        onOpenDeploy={(env) => {
          setDeployTargetEnv(env);
          setDeployModalOpen(true);
        }}
      />

      {/* Full-width Main Eval Workspace */}
      <EvalDashboard
        projectId={activeProjectId}
        projectName={activeProject?.name || "Project"}
        activeEnv={activeEnv}
        activeSuiteId={activeSuiteId}
        overview={overview}
        overviewVersion={overviewVersion}
        loading={overviewLoading}
        runningLogs={evalLogs}
        isEvalRunning={evalRunning}
        onSelectSuite={(sid) => {
          setActiveSuiteId(sid);
          if (activeProjectId) void loadOverview(activeProjectId, activeEnv, sid);
        }}
        onRefresh={() => {
          if (activeProjectId) {
            void loadOverview(activeProjectId, activeEnv, activeSuiteId);
            void loadProjects(activeProjectId, activeEnv);
          }
        }}
        onStartRun={handleStartEvalRun}
        onDiagnoseCase={handleDiagnoseCase}
        onOpenCreateSuite={() =>
          setSuiteModalState({ open: true, mode: "create" })
        }
        onOpenEditSuite={(sid) =>
          setSuiteModalState({ open: true, mode: "edit", suiteId: sid })
        }
        onOpenImportXlsx={() => setImportXlsxOpen(true)}
      />

      {/* Bottom-Right Floating AGY Agent Widget */}
      <AgentWidget
        project={activeProject}
        activeEnv={activeEnv}
        widgetMode={widgetMode}
        onChangeWidgetMode={setWidgetMode}
        conversations={wb.conversations}
        activeConversationId={wb.activeConvId}
        sessionStates={wb.sessionStates}
        onClearUnread={wb.markActiveSessionRead}
        workbenchProps={{
          apiBase: WORKBENCH_API_BASE,
          mode: wb.mode,
          onChangeMode: wb.setMode,
          sandboxStatus: wb.health?.sandbox_status,
          availableModels: wb.availableModels,
          selectedModel: wb.selectedModel,
          onSelectModel: wb.setSelectedModel,
          webSearchEnabled: wb.webSearchEnabled,
          onChangeWebSearch: wb.setWebSearchEnabled,
          webSearchHealth: wb.health?.web_search,
          authStatus: wb.authStatus,
          vertexProjectId: wb.health?.vertex_project_id,
          vertexLocation: wb.health?.vertex_location,
          slashCommands: wb.slashCommands,
          onSearchFiles: wb.searchWorkspaceFiles,
          conversations: wb.conversations,
          totalConversations: wb.totalConversations,
          hasMoreConversations: wb.hasMoreConversations,
          activeConversationId: wb.activeConvId,
          sessionStates: wb.sessionStates,
          messages: wb.messages,
          streaming: wb.streaming,
          onSelectConversation: wb.selectConversation,
          onNewConversation: () => {
            if (activeProjectId) void wb.createConversation(activeProjectId);
          },
          onCloseConversation: wb.closeConversation,
          onDeleteConversation: wb.deleteConversation,
          onSearchConversations: wb.searchConversations,
          onRenameConversation: wb.renameConversation,
          onSendMessage: (txt, files) => wb.sendMessage(txt, undefined, files),
          onStopStreaming: () => wb.stopStreaming(),
          onDecideApproval: wb.decideApproval,
          emptyTitle: `Maintainer ready for ${activeProject?.name || "Project"}`,
          emptyDescription:
            "Project-scoped chat across all configured environment repositories. Inspect Eval results, compare envs, apply fixes, and verify regressions.",
          quickPrompts,
          toolSummarizer: askToolSummarizer,
          notifications: wb.notifications,
          onChangeTheme: applyDocumentTheme,
        }}
      />

      <ProjectModal
        open={projectModalState.open}
        mode={projectModalState.mode}
        project={activeProject}
        onClose={() =>
          setProjectModalState((prev) => ({ ...prev, open: false }))
        }
        onSaveProject={handleSaveProject}
        onDeleteProject={handleDeleteProject}
      />

      <SuiteModal
        open={suiteModalState.open}
        mode={suiteModalState.mode}
        projectId={activeProjectId}
        env={activeEnv}
        suiteId={suiteModalState.suiteId}
        onClose={() =>
          setSuiteModalState((prev) => ({ ...prev, open: false }))
        }
        onSaved={(sid) => {
          setActiveSuiteId(sid);
          if (activeProjectId) {
            void loadOverview(activeProjectId, activeEnv, sid);
            void loadProjects(activeProjectId, activeEnv);
          }
        }}
        onDeleted={() => {
          setActiveSuiteId("");
          if (activeProjectId) {
            void loadOverview(activeProjectId, activeEnv);
            void loadProjects(activeProjectId, activeEnv);
          }
        }}
      />

      <ImportXlsxModal
        open={importXlsxOpen}
        projectId={activeProjectId}
        env={activeEnv}
        activeSuiteId={activeSuiteId}
        onClose={() => setImportXlsxOpen(false)}
        onImported={(sid) => {
          setActiveSuiteId(sid);
          if (activeProjectId) {
            void loadOverview(activeProjectId, activeEnv, sid);
            void loadProjects(activeProjectId, activeEnv);
          }
        }}
      />

      <GitDiffPanel
        open={gitDrawerOpen}
        onClose={() => setGitDrawerOpen(false)}
        project={activeProject}
        activeEnv={gitDrawerEnv}
        onChangeEnv={setGitDrawerEnv}
        gitInfoByEnv={gitInfoByEnv}
        loading={gitLoading}
        onRefresh={() => void loadAllGitDiffs(activeProject)}
        onOpenDeploy={(env) => {
          setDeployTargetEnv(env);
          setDeployModalOpen(true);
        }}
      />

      <DeployModal
        open={deployModalOpen}
        project={activeProject}
        initialTargetEnv={deployTargetEnv}
        onClose={() => setDeployModalOpen(false)}
        onDeployed={() => {
          void loadProjects(activeProjectId, activeEnv);
          void loadAllGitDiffs(activeProject);
        }}
      />

      <AuthLoginModal
        apiBase={WORKBENCH_API_BASE}
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
