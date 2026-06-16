import { apiClient } from "./client";

const EVALUATION_REQUEST_TIMEOUT_MS = 10 * 60 * 1000;

export interface SystemSummary {
  app_name: string;
  version: string;
  stage: string;
  frontend_stack: string;
  backend_stack: string;
}

export interface SystemRuntimeOverview {
  app_env: string;
  auth_enabled: boolean;
  langfuse_enabled: boolean;
  langfuse_capture_input_output: boolean;
  langfuse_prompt_management_enabled: boolean;
  database_backend: string;
  qdrant_backend: string;
  workflow_checkpointer_backend: string;
  workflow_checkpointer_label: string;
  llm_provider: string;
  llm_model: string;
  llm_allowed_models: string[];
  embedding_provider: string;
  embedding_model: string;
  embedding_allowed_models: string[];
}

export interface SystemResourceCounts {
  assistants_total: number;
  knowledge_bases_total: number;
  sessions_total: number;
}

export interface SystemSessionCounts {
  active: number;
  awaiting_clarification: number;
  awaiting_review: number;
}

export interface SystemTaskCounts {
  jobs_total: number;
  jobs_pending: number;
  jobs_running: number;
  jobs_failed: number;
  jobs_warning: number;
  jobs_breached: number;
  reviews_total: number;
  reviews_pending: number;
  reviews_escalated: number;
  reviews_warning: number;
  reviews_breached: number;
}

export interface SystemAlert {
  level: string;
  code: string;
  title: string;
  detail: string;
  count?: number | null;
}

export interface SystemReadinessCheck {
  status: string;
  code: string;
  title: string;
  detail: string;
}

export interface SystemReadinessSummary {
  overall_status: string;
  passed: number;
  warnings: number;
  failed: number;
  checks: SystemReadinessCheck[];
}

export interface SystemMaintenanceRequest {
  reconcile_overdue_reviews?: boolean;
  retry_failed_jobs?: boolean;
  job_retry_limit?: number | null;
}

export interface SystemMaintenanceResult {
  executed_at: string;
  reconcile_overdue_reviews_count: number;
  retried_job_count: number;
  retried_job_ids: string[];
  skipped_job_ids: string[];
}

export interface EvaluationRunRequest {
  assistant_id: string;
  dataset_key?: string;
  dataset_path?: string;
  limit?: number | null;
  top_k?: number;
  write_scores_to_langfuse?: boolean;
}

export interface EvaluationRunItemSummary {
  item_id: string;
  question: string;
  trace_id: string;
  trace_url?: string | null;
  answer_preview: string;
  fallback_reason?: string | null;
  retrieval_count: number;
  citation_count: number;
  citation_files: string[];
  prompt_name: string;
  prompt_version?: number | null;
  prompt_source: string;
  average_score: number;
  scores: Record<string, number>;
  error: string;
}

export interface EvaluationRunResponse {
  run_id: string;
  assistant_id: string;
  assistant_name: string;
  dataset_key: string;
  dataset_path: string;
  dataset_item_count: number;
  success_count: number;
  failure_count: number;
  average_scores: Record<string, number>;
  items: EvaluationRunItemSummary[];
}

export interface EvaluationDatasetSummary {
  key: string;
  label: string;
  description: string;
  path: string;
}

export interface SystemOverview {
  health_status: string;
  summary: SystemSummary;
  runtime: SystemRuntimeOverview;
  resources: SystemResourceCounts;
  sessions: SystemSessionCounts;
  tasks: SystemTaskCounts;
  alerts: SystemAlert[];
  readiness: SystemReadinessSummary;
}

export async function fetchSystemOverview(): Promise<SystemOverview> {
  const response = await apiClient.get<SystemOverview>("/system/overview");
  return response.data;
}

export async function runSystemMaintenance(
  payload: SystemMaintenanceRequest,
): Promise<SystemMaintenanceResult> {
  const response = await apiClient.post<SystemMaintenanceResult>(
    "/system/maintenance/run",
    payload,
  );
  return response.data;
}

export async function runSystemEvaluation(
  payload: EvaluationRunRequest,
): Promise<EvaluationRunResponse> {
  const response = await apiClient.post<EvaluationRunResponse>(
    "/system/evaluations/run",
    payload,
    {
      timeout: EVALUATION_REQUEST_TIMEOUT_MS,
    },
  );
  return response.data;
}

export async function fetchEvaluationDatasets(): Promise<EvaluationDatasetSummary[]> {
  const response = await apiClient.get<EvaluationDatasetSummary[]>(
    "/system/evaluations/datasets",
  );
  return response.data;
}
