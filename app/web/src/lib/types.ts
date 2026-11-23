export type {
  ChatMessage,
  ConversationRecord,
  ExecutionMode,
  ModelOption,
  PendingApprovalItem,
  SandboxStatus,
  ToolEvent,
  WorkbenchHealthStatus as HealthStatus,
} from "@ag-workbench/types";

export type TargetEnv = "dev" | "uat";

export interface WorkspaceSummary {
  id: string;
  name: string;
  path: string;
  uat_path: string | null;
  uat_exists: boolean;
  env: string;
  exists: boolean;
  has_uat_config: boolean;
  has_uat_questions: boolean;
  has_uat_results: boolean;
  branch: string | null;
  dirty_count: number;
  unpushed_count: number;
}

export interface GitChangedFile {
  status: string;
  path: string;
}

export interface WorkspaceGitInfo {
  is_git_repo: boolean;
  git_toplevel: string | null;
  service_subpath: string;
  branch: string | null;
  remote_url: string | null;
  changed_files: GitChangedFile[];
  unpushed_commits: string[];
  diff: string;
}

export interface DeployFileItem {
  path: string;
  status: string;
  protected: boolean;
  reason?: string | null;
}

export interface DeployPreview {
  target_env: TargetEnv;
  mode: "direct_push" | "promote_from_dev";
  workspace_id: string;
  workspace_name: string;
  repo_toplevel: string | null;
  service_subpath: string;
  branch: string | null;
  remote_url: string | null;
  changed_files: DeployFileItem[];
  protected_files: DeployFileItem[];
  unpushed_commits: string[];
  diff: string;
  can_deploy: boolean;
  blocking_reason: string | null;
  suggested_commit_message: string;
}

export interface DeployResult {
  ok: boolean;
  target_env: TargetEnv;
  commit_sha: string | null;
  branch: string;
  remote_url: string | null;
  pushed_files: string[];
  logs: string[];
}

export interface UatReview {
  status?: string;
  score?: number;
  behavior_check?: string;
  answer_check?: string;
  comment?: string;
}

export interface UatTurnResult {
  turn: number;
  question: string;
  raw_response?: {
    text?: string;
    sources?: string[];
    error?: string;
  };
  expected_answer?: string;
  expected_behavior?: string;
  uat_review?: UatReview;
}

export interface UatCaseResult {
  id: string;
  uat_review?: UatReview;
  turns: UatTurnResult[];
}

export interface UatQuestionCase {
  id: string;
  turns: Array<{
    question: string;
    expected_answer?: string;
    expected_behavior?: string;
  }>;
}

export interface UatSummaryStats {
  total_cases: number;
  evaluated_cases: number;
  pass_count: number;
  partial_count: number;
  fail_count: number;
  total_score: number;
  score_pct: number;
  failing_ids: string[];
}

export interface UatOverview {
  workspace_id: string;
  workspace_name: string;
  has_config: boolean;
  has_questions: boolean;
  has_results: boolean;
  config: Record<string, unknown> | null;
  rubric_preview: string;
  questions_count: number;
  questions: UatQuestionCase[];
  results: UatCaseResult[];
  result_files: string[];
  summary: UatSummaryStats;
  results_updated_at: number | null;
}
