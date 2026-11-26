export type {
  AuthStatus,
  ChatAttachment,
  ChatMessage,
  ConversationListResponse,
  ConversationRecord,
  ConversationSummary,
  ExecutionMode,
  ModelOption,
  PendingApprovalItem,
  SandboxStatus,
  SessionRuntimeState,
  SlashCommandItem,
  ToolEvent,
  WorkbenchHealthStatus as HealthStatus,
  WorkbenchNotificationControl,
  WorkspaceFileItem,
} from "@ag-workbench/types";
export type { BrowserIconStatus } from "@ag-workbench/index";

export type EnvName = "sbx" | "dev" | "uat" | "prod";
export const ENV_ORDER: EnvName[] = ["sbx", "dev", "uat", "prod"];
export const ENV_LABELS: Record<EnvName, string> = {
  sbx: "Sandbox",
  dev: "DEV",
  uat: "UAT",
  prod: "PROD",
};

export type TargetEnv = EnvName;
export type DeployMode = "auto" | "direct_push" | "promote" | "promote_from_dev";

export interface EnvGitSummary {
  env: EnvName;
  path: string;
  exists: boolean;
  branch: string | null;
  dirty_count: number;
  unpushed_count: number;
  remote_url: string | null;
}

export interface EnvEvalBrief {
  suite_count: number;
  default_suite_id: string | null;
  default_suite_name: string | null;
  endpoint: string | null;
  total_cases: number;
  evaluated_cases: number;
  pass_count: number;
  partial_count: number;
  fail_count: number;
  score_pct: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  active_env: EnvName;
  path: string;
  exists: boolean;
  environments: Partial<Record<EnvName, string>>;
  configured_envs: EnvName[];
  env_git: Partial<Record<EnvName, EnvGitSummary>>;
  env_eval: Partial<Record<EnvName, EnvEvalBrief>>;
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
  env?: EnvName;
}

export interface DeployFileItem {
  path: string;
  status: string;
  protected: boolean;
  reason?: string | null;
}

export interface CompareEnvsResult {
  source_env: EnvName;
  target_env: EnvName;
  source_path: string;
  target_path: string;
  source_branch: string | null;
  target_branch: string | null;
  in_sync: boolean;
  changed_files: DeployFileItem[];
  protected_files: DeployFileItem[];
  target_only_files: string[];
  diff: string;
  diff_truncated: boolean;
}

export interface DeployPreview {
  target_env: TargetEnv;
  source_env: TargetEnv | null;
  mode: "direct_push" | "promote" | "promote_from_dev";
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
  has_direct_target_changes?: boolean;
  direct_target_files?: string[];
  has_direct_uat_changes?: boolean;
  direct_uat_files?: string[];
  overlap_conflict_files?: string[];
  available_source_envs?: EnvName[];
}

export interface DeployResult {
  ok: boolean;
  target_env: TargetEnv;
  source_env?: TargetEnv | null;
  commit_sha: string | null;
  branch: string;
  remote_url: string | null;
  pushed_files: string[];
  logs: string[];
}

export interface EvalReview {
  status?: string;
  score?: number;
  behavior_check?: string;
  answer_check?: string;
  comment?: string;
}

export interface EvalTurnResult {
  turn: number;
  question: string;
  expected_answer?: string;
  expected_behavior?: string;
  raw_response?: {
    text?: string;
    sources?: string[];
    error?: string;
  };
  eval_review?: EvalReview;
  uat_review?: EvalReview;
}

export type EvalCaseStatus = "PASS" | "PARTIAL" | "FAIL" | "PENDING";

export interface EvalCaseSummary {
  id: string;
  sort_order: number;
  first_question: string;
  turn_count: number;
  tags: string[];
  status: EvalCaseStatus;
  score: number | null;
  comment: string;
  updated_at: number | null;
  job_id: string | null;
}

export interface EvalCaseDetail {
  id: string;
  suite_id: string;
  sort_order: number;
  turn_count: number;
  tags: string[];
  eval_review: EvalReview;
  turns: EvalTurnResult[];
  job_id: string | null;
  updated_at: number | null;
}

export interface EvalSummaryStats {
  total_cases: number;
  evaluated_cases: number;
  pass_count: number;
  partial_count: number;
  fail_count: number;
  total_score: number;
  score_pct: number;
  failing_ids: string[];
  updated_at?: number | null;
}

export interface EvalSuiteSummary {
  id: string;
  project_id: string;
  env: EnvName;
  slug: string;
  name: string;
  description: string;
  endpoint: string;
  source_xlsx_name: string | null;
  is_default: boolean;
  total_cases: number;
  evaluated_cases: number;
  pass_count: number;
  partial_count: number;
  fail_count: number;
  total_score: number;
  score_pct: number;
  last_eval_at: number | null;
  created_at: number;
  updated_at: number;
}

export interface EvalActiveSuiteMeta {
  id: string;
  slug: string;
  name: string;
  description: string;
  endpoint: string;
  source_xlsx_name: string | null;
  is_default: boolean;
  has_template_xlsx: boolean;
  excel_mapping: Record<string, unknown>;
  updated_at: number;
}

export interface EvalSuiteFull {
  id: string;
  project_id: string;
  env: EnvName;
  slug: string;
  name: string;
  description: string;
  config: Record<string, unknown>;
  rubric_md: string;
  excel_mapping: Record<string, unknown>;
  source_xlsx_name: string | null;
  is_default: boolean;
  created_at: number;
  updated_at: number;
}

export interface EvalRunRecord {
  job_id: string;
  project_id: string;
  env: EnvName;
  suite_id: string;
  status: string;
  exit_code: number | null;
  endpoint: string;
  summary: Partial<EvalSummaryStats>;
  started_at: number;
  finished_at: number | null;
}

export interface EvalOverview {
  project_id: string;
  project_name: string;
  env: EnvName;
  suites_total: number;
  suites: EvalSuiteSummary[];
  active_suite: EvalActiveSuiteMeta | null;
  has_config: boolean;
  has_questions: boolean;
  has_results: boolean;
  has_template_xlsx: boolean;
  config: Record<string, unknown> | null;
  rubric_preview: string;
  questions_count: number;
  summary: EvalSummaryStats;
  cases: EvalCaseSummary[];
  cases_total: number;
  cases_has_more: boolean;
  runs: EvalRunRecord[];
  results_updated_at: number | null;
}

export interface InspectXlsxSampleRow {
  row: number;
  cells: Record<string, string>;
}

export interface InspectXlsxSheetDetail {
  name: string;
  non_empty_rows: number;
  sample_rows: InspectXlsxSampleRow[];
}

export interface InspectXlsxResponse {
  filename: string;
  sheets: string[];
  details: InspectXlsxSheetDetail[];
  suggested_mapping: Record<string, unknown>;
}
