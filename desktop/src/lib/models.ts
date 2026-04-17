export function isEmbeddingModelName(modelName: string): boolean {
  const lowered = String(modelName || '').trim().toLowerCase();
  if (!lowered) return false;
  return lowered.includes('embed') || lowered.includes('embedding') || lowered.includes('nomic');
}

export function filterChatCapableModels<T extends { name: string }>(models: T[]): T[] {
  return models.filter((model) => !isEmbeddingModelName(model.name));
}

export type RuntimeProcessState = 'starting' | 'running' | 'degraded' | 'stopped' | 'offline';
export type RuntimeReadinessPhase = 'spawning' | 'binding_dashboard' | 'warming_operator_surface' | 'ready' | 'offline';

export interface BackendRuntimeStatus {
  running: boolean;
  port: number;
  healthy: boolean;
  attached_to_existing?: boolean;
  start_in_progress?: boolean;
  process_state: RuntimeProcessState;
  readiness_phase: RuntimeReadinessPhase;
  dashboard_bound: boolean;
  operator_api_ready: boolean;
  adaptive_ready: boolean;
  stale_process_cleanup: boolean;
  desktop_log_path?: string | null;
  last_error?: string | null;
}

export interface AdaptiveSuggestion {
  suggestion_id: string;
  category: string;
  title: string;
  summary: string;
  confidence: number;
  rationale: string;
  proposed_action: string;
  risk_level: 'low' | 'medium' | 'high';
  project_scope?: string | null;
  requires_approval: boolean;
  state?: string;
  score?: number;
  created_at?: number;
}

export interface LearningDiff {
  cycle_id: string;
  behavior_change_summary: string;
  probation_status: string;
  approval_status: string;
  impacted_artifacts?: string[];
  source_events?: string[];
  reviewer_note?: string;
  last_error?: string;
  created_at?: number;
}

export interface ChangeReceipt {
  receipt_id: string;
  task_id: string;
  operation_list: string[];
  operations: string[];
  files_changed: string[];
  integrations_touched: string[];
  memory_updated?: string[] | boolean;
  artifacts: Array<Record<string, unknown>>;
  rollback_token?: string | null;
  rollback_available?: boolean;
  snapshot_id?: string | null;
  summary?: string;
  created_at?: number;
}

export interface ProjectContextProfile {
  project_id: string;
  title: string;
  paths: string[];
  agents_md_summary: string;
  active_skills: string[];
  preferred_provider: string;
  preferred_model: string;
  recent_tasks: Array<{ task_id?: string; title?: string; status?: string }>;
  last_known_open_work: string[];
  connected_integrations: string[];
  running_agents: string[];
  autonomy_mode?: string;
  created_at?: number;
  updated_at?: number;
}

export interface TeachingArtifact {
  entry_id: string;
  title: string;
  transcript: string;
  template_candidate?: string;
  workflow_candidate?: Record<string, unknown>;
  skill_candidate?: Record<string, unknown>;
  tags?: string[];
  promotion_state?: string;
  created_at?: number;
}

export interface ProactiveRoutine {
  routine_id: string;
  title: string;
  trigger_pattern: string;
  action_template: string;
  risk_level?: string;
  autonomy_class?: string;
  probation_status?: string;
  success_count?: number;
  failure_count?: number;
  last_run_at?: number | null;
  name?: string;
  proposed_workflow?: string;
  state?: string;
}
