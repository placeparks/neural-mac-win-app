// NeuralClaw Desktop — API Client
// Maps to the actual Dashboard + WebChat backend routes

import { invoke } from '@tauri-apps/api/core';
import { DASHBOARD_BASE, API_DEFAULT_TIMEOUT_MS, API_LONG_TIMEOUT_MS, API_HEALTH_TIMEOUT_MS, API_CHAT_TIMEOUT_MS } from './constants';
import { ALL_PROVIDERS } from './theme';
import type {
  AdaptiveSuggestion,
  BackendRuntimeStatus,
  ChangeReceipt,
  LearningDiff,
  ProjectContextProfile,
  ProactiveRoutine,
  TeachingArtifact,
} from './models';

async function readApiError(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => 'Unknown');
  if (!text) return 'Unknown';
  try {
    const parsed = JSON.parse(text) as { error?: string; message?: string };
    return parsed.error || parsed.message || text;
  } catch {
    return text;
  }
}

/**
 * fetch wrapper with hard timeout via AbortController.
 * Without this, a hung gateway makes UI requests wait forever.
 */
async function timedFetch(input: RequestInfo, init: RequestInit = {}, timeoutMs = API_DEFAULT_TIMEOUT_MS): Promise<Response> {
  const ctrl = new AbortController();
  const handle = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: init.signal ?? ctrl.signal });
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs}ms (gateway unreachable or stalled)`);
    }
    throw e;
  } finally {
    clearTimeout(handle);
  }
}

async function dashboardGet<T = unknown>(path: string, timeoutMs = API_DEFAULT_TIMEOUT_MS): Promise<T> {
  const resp = await timedFetch(`${DASHBOARD_BASE}${path}`, {}, timeoutMs);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json() as Promise<T>;
}

async function dashboardPost<T = unknown>(path: string, body?: unknown, timeoutMs = API_LONG_TIMEOUT_MS): Promise<T> {
  const resp = await timedFetch(`${DASHBOARD_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  }, timeoutMs);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json() as Promise<T>;
}

async function dashboardDelete<T = unknown>(path: string, timeoutMs = API_DEFAULT_TIMEOUT_MS): Promise<T> {
  const resp = await timedFetch(`${DASHBOARD_BASE}${path}`, { method: 'DELETE' }, timeoutMs);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json() as Promise<T>;
}

// ── Health (Dashboard :8080/health) ──

export interface HealthResponse {
  status: string;
  version?: string;
  uptime?: string;
  readiness?: string;
  runtime?: Partial<BackendRuntimeStatus>;
}

export async function getHealth(): Promise<HealthResponse> {
  return dashboardGet<HealthResponse>('/health', API_HEALTH_TIMEOUT_MS);
}

export async function getBackendRuntimeStatus(): Promise<BackendRuntimeStatus> {
  return invoke<BackendRuntimeStatus>('get_backend_status');
}

export async function getReady(): Promise<{ status: string }> {
  return dashboardGet('/ready');
}

// ── Stats (Dashboard :8080/api/stats) ──

export interface StatsResponse {
  provider?: string;
  interactions?: number;
  success_rate?: number;
  skills?: number;
  channels?: string;
  uptime?: string;
}

export async function getStats(): Promise<StatsResponse> {
  return dashboardGet<StatsResponse>('/api/stats');
}

// ── Memory (Dashboard :8080/api/memory) ──

export interface MemoryStats {
  episodic_count: number;
  semantic_count: number;
  procedural_count: number;
  vector_count?: number;
  identity_count?: number;
}

export async function getMemoryStats(): Promise<MemoryStats> {
  return dashboardGet<MemoryStats>('/api/memory');
}

export type MemoryStore = 'all' | 'episodic' | 'semantic' | 'procedural' | 'vector' | 'identity';

export interface MemoryItem {
  id: string;
  store: MemoryStore;
  title: string;
  preview: string;
  content?: string;
  timestamp?: number | null;
  updated_at?: number | null;
  pinned?: boolean;
  score?: number | null;
  can_edit: boolean;
  can_pin: boolean;
  can_delete: boolean;
  metadata: Record<string, unknown>;
}

export interface MemoryProvenanceItem {
  memory_type: string;
  item_id: string;
  title: string;
  excerpt: string;
  reason: string;
  scope: string;
  score?: number | null;
  metadata?: Record<string, unknown>;
}

export interface MemoryExportResponse {
  ok: boolean;
  encrypted: boolean;
  payload: string;
  salt?: string;
  digest?: string;
}

export interface MemoryImportResponse {
  ok: boolean;
  imported?: Record<string, number>;
  error?: string;
}

export interface MemoryRetentionResponse {
  ok: boolean;
  deleted?: Record<string, number>;
  retention_days?: Record<string, number>;
  error?: string;
}

export async function clearMemory(payload?: {
  stores?: MemoryStore[];
  clear_history?: boolean;
}): Promise<{
  ok: boolean;
  episodic_deleted?: number;
  semantic_deleted?: number;
  procedural_deleted?: number;
  vector_deleted?: number;
  identity_deleted?: number;
  history_cleared?: boolean;
}> {
  return dashboardPost('/api/memory/clear', payload || {});
}

export async function getMemoryItems(
  store: MemoryStore,
  query = '',
  limit = 50,
): Promise<{ items: MemoryItem[]; store: MemoryStore }> {
  const params = new URLSearchParams({
    store,
    query,
    limit: String(limit),
  });
  return dashboardGet(`/api/memory/items?${params.toString()}`);
}

export async function updateMemoryItem(
  store: Exclude<MemoryStore, 'all' | 'vector'>,
  itemId: string,
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; item_id?: string; store?: string; error?: string | null }> {
  const resp = await timedFetch(`${DASHBOARD_BASE}/api/memory/items/${encodeURIComponent(store)}/${encodeURIComponent(itemId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return resp.json();
}

export async function deleteMemoryItem(
  store: Exclude<MemoryStore, 'all'>,
  itemId: string,
): Promise<{ ok: boolean; item_id?: string; store?: string; error?: string | null }> {
  return dashboardDelete(`/api/memory/items/${encodeURIComponent(store)}/${encodeURIComponent(itemId)}`);
}

export async function pinMemoryItem(
  store: 'episodic' | 'semantic',
  itemId: string,
): Promise<{ ok: boolean; item_id?: string; store?: string; error?: string | null }> {
  return dashboardPost(`/api/memory/items/${encodeURIComponent(store)}/${encodeURIComponent(itemId)}/pin`, {});
}

export async function exportMemoryBackup(payload?: {
  stores?: MemoryStore[];
  passphrase?: string;
}): Promise<MemoryExportResponse> {
  return dashboardPost('/api/memory/export', payload || {});
}

export async function importMemoryBackup(payload: {
  payload: string;
  encrypted?: boolean;
  salt?: string;
  digest?: string;
  passphrase?: string;
}): Promise<MemoryImportResponse> {
  return dashboardPost('/api/memory/import', payload);
}

export async function runMemoryRetention(): Promise<MemoryRetentionResponse> {
  return dashboardPost('/api/memory/retention', {});
}

// ── Message (Dashboard :8080/api/message — for quick test messages) ──

export async function sendDashboardMessage(content: string): Promise<{ ok: boolean; response: string }> {
  return dashboardPost('/api/message', { content });
}

export interface ChatSessionMetadata {
  targetAgent?: string | null;
  selectedModel?: string | null;
  selectedProvider?: string | null;
  baseUrl?: string | null;
  effectiveModel?: string | null;
  fallbackReason?: string | null;
  teachingMode?: boolean | null;
  autonomyMode?: 'observe-only' | 'suggest-first' | 'auto-run-low-risk' | 'policy-driven-autonomous' | null;
  projectContextId?: string | null;
  channelStyleProfile?: Record<string, unknown> | null;
}

export interface ChatAttachmentPayload {
  name: string;
  content: string;
  mimeType: string;
  kind: 'image' | 'document';
}

export interface ChatSendPayload {
  content: string;
  targetAgent?: string | null;
  model?: string | null;
  provider?: string | null;
  baseUrl?: string | null;
  sessionId?: string | null;
  teachingMode?: boolean | null;
  autonomyMode?: string | null;
  projectContextId?: string | null;
  channelStyleProfile?: Record<string, unknown> | null;
  media?: Array<Record<string, unknown>>;
  documents?: Array<Record<string, unknown>>;
}

export interface ConfidenceContract {
  response?: string;
  confidence?: number;
  source?: string;
  alternatives_considered?: number;
  uncertainty_factors?: string[];
  tool_calls_made?: number;
  evidence_sources?: string[];
  escalation_recommendation?: string;
  retry_rationale?: string;
}

export interface ChatSendResponse {
  ok: boolean;
  response?: string;
  routed_to?: string;
  model?: string | null;
  requested_model?: string | null;
  effective_model?: string | null;
  fallback_reason?: string | null;
  task_id?: string | null;
  memory_provenance?: MemoryProvenanceItem[];
  memory_scopes?: string[];
  confidence_contract?: ConfidenceContract;
  error?: string;
}

export async function sendChatMessage(payload: ChatSendPayload): Promise<ChatSendResponse> {
  return dashboardPost<ChatSendResponse>('/api/message', payload, API_CHAT_TIMEOUT_MS);
}

// ── Agents (Dashboard :8080/api/agents) ──

export interface Agent {
  name: string;
  status: string;
  capabilities?: string[];
}

export async function getAgents(): Promise<Agent[]> {
  return dashboardGet<Agent[]>('/api/agents');
}

export async function spawnAgent(name: string, description: string, capabilities: string, endpoint: string): Promise<{ ok: boolean }> {
  return dashboardPost('/api/spawn', { name, description, capabilities, endpoint });
}

export async function despawnAgent(name: string): Promise<{ ok: boolean }> {
  return dashboardPost('/api/despawn', { name });
}

// ── Federation (Dashboard :8080/api/federation) ──

export interface FederationData {
  total_nodes: number;
  online_nodes: number;
  nodes: { name: string; status: string; trust_score: number; capabilities?: string[] }[];
}

export async function getFederation(): Promise<FederationData> {
  return dashboardGet<FederationData>('/api/federation');
}

export async function joinFederation(endpoint: string): Promise<{ ok: boolean }> {
  return dashboardPost('/api/federation/join', { endpoint });
}

// ── Features (Dashboard :8080/api/features) ──

export async function getFeatures(): Promise<Record<string, { label: string; value: boolean; live: boolean }>> {
  return dashboardGet('/api/features');
}

export async function setFeature(feature: string, value: boolean): Promise<{ ok: boolean }> {
  return dashboardPost('/api/features', { feature, value });
}

// ── Bus (Dashboard :8080/api/bus) ──

export interface BusEvent {
  id?: string;
  type: string;
  source?: string;
  data_preview?: string;
  timestamp?: number;
  correlation_id?: string | null;
  level?: 'info' | 'success' | 'warning' | 'error';
}

export async function getBusEvents(): Promise<BusEvent[]> {
  return dashboardGet<BusEvent[]>('/api/bus');
}

// ── Traces (Dashboard :8080/api/traces) ──

export interface Trace {
  category: string;
  message: string;
  timestamp: number;
  data?: Record<string, unknown>;
}

export async function getTraces(limit = 50): Promise<Trace[]> {
  return dashboardGet<Trace[]>(`/api/traces?limit=${limit}`);
}

// ── Config (Dashboard :8080/config) ──

export async function getConfig(): Promise<Record<string, unknown>> {
  return dashboardGet('/config');
}

export interface ProviderDefaults {
  provider: string;
  primary: string;
  baseUrl: string;
  model: string;
}

const KNOWN_PROVIDER_IDS: Set<string> = new Set(ALL_PROVIDERS.map((provider) => provider.id));

function normalizeProviderId(provider: string): string {
  const normalized = String(provider || '').trim().toLowerCase();
  if (normalized === 'meta' || normalized === 'ollama') return 'local';
  return normalized;
}

function resolvePrimaryProviderId(providers: Record<string, any>): string {
  const requested = normalizeProviderId(String(providers.primary || ''));
  if (requested && KNOWN_PROVIDER_IDS.has(requested)) {
    return requested;
  }
  return 'local';
}

function resolveRequestedProviderId(providers: Record<string, any>, provider: string): string {
  const requested = normalizeProviderId(provider);
  if (!requested || requested === 'auto' || requested === 'default' || requested === 'primary') {
    return resolvePrimaryProviderId(providers);
  }
  if (KNOWN_PROVIDER_IDS.has(requested)) {
    return requested;
  }
  return resolvePrimaryProviderId(providers);
}

export async function getProviderDefaults(provider: string): Promise<ProviderDefaults> {
  const parsed = await getConfig();
  const providers = (parsed.providers as Record<string, any> | undefined) || {};
  const primary = resolvePrimaryProviderId(providers);
  const resolvedProvider = resolveRequestedProviderId(providers, provider);
  const section = (providers[resolvedProvider] as Record<string, any> | undefined) || {};
  return {
    provider: resolvedProvider,
    primary,
    baseUrl: String(section.base_url || ''),
    model: String(section.model || ''),
  };
}

export async function getPrimaryProviderDefaults(): Promise<ProviderDefaults> {
  const parsed = await getConfig();
  const providers = (parsed.providers as Record<string, any> | undefined) || {};
  const primary = resolvePrimaryProviderId(providers);
  const section = (providers[primary] as Record<string, any> | undefined) || {};
  return {
    provider: primary,
    primary,
    baseUrl: String(section.base_url || ''),
    model: String(section.model || ''),
  };
}

export async function updateDashboardConfig(
  updates: Record<string, unknown>,
): Promise<{ ok: boolean; restart_required?: boolean; config?: Record<string, unknown>; error?: string }> {
  return dashboardPost('/api/config', updates);
}

export interface ChannelSnapshot {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  ready?: boolean;
  paired?: boolean;
  status?: string;
  status_detail?: string;
  can_enable?: boolean;
  running: boolean;
  trust_mode: string;
  token_present: boolean;
  restart_required: boolean;
  validation_errors?: string[];
  fields?: Array<{
    key: string;
    label: string;
    kind: string;
    placeholder?: string;
    description?: string;
    required?: boolean;
  }>;
  extra: Record<string, unknown>;
}

export interface ChannelUpdatePayload {
  enabled: boolean;
  trust_mode: string;
  secret?: string;
  extra?: Record<string, unknown>;
}

export async function getChannels(): Promise<ChannelSnapshot[]> {
  return dashboardGet('/api/channels');
}

export async function updateChannel(
  channelName: string,
  payload: ChannelUpdatePayload,
): Promise<{ ok: boolean; restart_required?: boolean; channel?: ChannelSnapshot; error?: string }> {
  return dashboardPost(`/api/channels/${encodeURIComponent(channelName)}`, payload);
}

export async function testChannel(
  channelName: string,
  payload: Partial<ChannelUpdatePayload>,
): Promise<{ ok: boolean; message?: string; error?: string }> {
  return dashboardPost(`/api/channels/${encodeURIComponent(channelName)}/test`, payload);
}

export interface ChannelPairResponse {
  ok: boolean;
  paired?: boolean;
  auth_dir?: string;
  message?: string;
  error?: string;
  qr_data?: string;
  qr_data_url?: string;
  pairing_code?: string;
}

export async function pairChannel(
  channelName: string,
  payload: Partial<ChannelUpdatePayload>,
): Promise<ChannelPairResponse> {
  return dashboardPost(`/api/channels/${encodeURIComponent(channelName)}/pair`, payload);
}

export async function resetChannel(
  channelName: string,
): Promise<{ ok: boolean; channel?: ChannelSnapshot; error?: string }> {
  return dashboardPost(`/api/channels/${encodeURIComponent(channelName)}/reset`, {});
}

// ── Skills (Dashboard :8080/skills) ──

export interface RuntimeSkillInfo {
  name: string;
  description: string;
  version?: string;
  tool_count: number;
  capabilities: string[];
}

export async function getSkills(): Promise<RuntimeSkillInfo[]> {
  return dashboardGet<RuntimeSkillInfo[]>('/skills');
}

// ── Workspace ──

export interface WorkspaceEntry {
  name: string;
  path: string;
  type: 'dir' | 'file';
  agents_md?: string | null;
  children?: WorkspaceEntry[];
}

export interface WorkspaceStructure {
  root: string;
  entries: WorkspaceEntry[];
  claims: WorkspaceClaim[];
}

export interface WorkspaceClaim {
  claim_id: string;
  agent_name: string;
  path: string;
  purpose: string;
  claimed_at: number;
  expires_at: number;
}

export interface ProjectInfo {
  name: string;
  path: string;
  template?: string;
  description?: string;
  agents_md?: string;
  files?: string[];
  created_at?: string;
}

export async function getWorkspaceStructure(includeHidden = false): Promise<WorkspaceStructure> {
  return dashboardGet<WorkspaceStructure>(`/api/workspace/structure?include_hidden=${includeHidden}`);
}

export async function getWorkspaceProjects(): Promise<{ projects: ProjectInfo[] }> {
  return dashboardGet<{ projects: ProjectInfo[] }>('/api/workspace/projects');
}

export async function scaffoldProject(payload: {
  project_name: string;
  template: string;
  description?: string;
  author?: string;
  claim_directory?: boolean;
}): Promise<{ ok: boolean; path?: string; files_created?: string[]; error?: string }> {
  return dashboardPost('/api/workspace/projects', payload);
}

export async function getProjectInfo(name: string): Promise<ProjectInfo> {
  return dashboardGet<ProjectInfo>(`/api/workspace/projects/${encodeURIComponent(name)}`);
}

export async function addToProject(
  name: string,
  component: string,
): Promise<{ ok: boolean; added?: string[]; error?: string }> {
  return dashboardPost(`/api/workspace/projects/${encodeURIComponent(name)}/component`, { component });
}

export async function getWorkspaceClaims(): Promise<WorkspaceClaim[]> {
  return dashboardGet<WorkspaceClaim[]>('/api/workspace/claims');
}

export async function claimWorkspaceDir(path: string, purpose?: string): Promise<{ ok: boolean; claim_id?: string; error?: string }> {
  return dashboardPost('/api/workspace/claim', { path, purpose: purpose || '' });
}

export async function releaseWorkspaceDir(path: string): Promise<{ ok: boolean; error?: string }> {
  const resp = await timedFetch(`${DASHBOARD_BASE}/api/workspace/claim`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json();
}

// ── Skills (available + templates) ──

export interface SkillInfo {
  name: string;
  description: string;
  source: string;
  tool_count: number;
  tools: { name: string; description: string }[];
}

export async function getAvailableSkills(sourceFilter = 'all'): Promise<{ skills: SkillInfo[]; total: number }> {
  return dashboardGet(`/api/skills/available?source_filter=${sourceFilter}`);
}

export async function getSkillTemplate(skillType = 'basic'): Promise<{ template: string; skill_type: string }> {
  return dashboardGet(`/api/skills/template?skill_type=${encodeURIComponent(skillType)}`);
}

// ── Agent Definitions (persistent) ──

export interface AgentDefinition {
  agent_id: string;
  name: string;
  description: string;
  capabilities: string[];
  provider: string;
  model: string;
  base_url: string;
  api_key?: string;
  system_prompt: string;
  memory_namespace: string;
  auto_start: boolean;
  created_at: number;
  updated_at: number;
  metadata: Record<string, unknown>;
}

export interface RunningAgent {
  name: string;
  description: string;
  status: 'online' | 'busy' | 'offline' | string;
  capabilities: string[];
  active_tasks: number;
  source: string;
  endpoint: string;
  provider?: string;
  model?: string;
  requested_model?: string;
  effective_model?: string;
  base_url?: string;
  memory_namespace?: string;
  last_task_at?: number | null;
  avg_latency_ms?: number | null;
  token_usage?: { input: number; output: number; total: number };
  last_error?: string | null;
  success_count?: number;
  failure_count?: number;
  recent_tasks?: Array<{ task: string; result_preview: string; success: boolean; latency_ms: number; timestamp: number }>;
  recent_logs?: Array<{ timestamp: number; message: string; level: string }>;
}

export interface AgentActivityEvent {
  id: string;
  from_agent: string;
  to_agent: string;
  message_type: string;
  content: string;
  payload?: Record<string, unknown>;
  timestamp: number;
}

export interface AgentMemorySnapshot {
  ok: boolean;
  namespace: string;
  episodic: {
    id: string;
    content: string;
    timestamp: number;
    source: string;
    importance: number;
  }[];
  semantic: {
    subject: string;
    predicate: string;
    object: string;
    confidence: number;
  }[];
  procedural: {
    id: string;
    name: string;
    description: string;
    success_rate: number;
    last_used: number;
  }[];
}

export interface SharedTaskDetails {
  ok: boolean;
  task: {
    task_id: string;
    agents: string[];
    status: string;
    created_at: number;
  };
  memories: {
    id: string;
    from_agent: string;
    content: string;
    memory_type: string;
    timestamp: number;
  }[];
}

export async function getAgentDefinitions(): Promise<AgentDefinition[]> {
  return dashboardGet<AgentDefinition[]>('/api/agents/definitions');
}

export async function createAgentDefinition(defn: Partial<AgentDefinition>): Promise<{ ok: boolean; agent_id?: string; error?: string }> {
  const resp = await timedFetch(`${DASHBOARD_BASE}/api/agents/definitions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(defn),
  });
  return resp.json();
}

export async function updateAgentDefinition(id: string, updates: Partial<AgentDefinition>): Promise<{ ok: boolean; error?: string }> {
  const resp = await timedFetch(`${DASHBOARD_BASE}/api/agents/definitions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  return resp.json();
}

export async function deleteAgentDefinition(id: string): Promise<{ ok: boolean }> {
  return dashboardDelete(`/api/agents/definitions/${id}`);
}

export async function spawnDefinedAgent(id: string): Promise<{ ok: boolean; name?: string; error?: string }> {
  return dashboardPost(`/api/agents/definitions/${id}/spawn`, {});
}

export async function despawnDefinedAgent(id: string): Promise<{ ok: boolean }> {
  return dashboardPost(`/api/agents/definitions/${id}/despawn`, {});
}

export async function getRunningAgents(): Promise<RunningAgent[]> {
  return dashboardGet<RunningAgent[]>('/api/agents/running');
}

export async function getAgentActivity(limit = 50): Promise<AgentActivityEvent[]> {
  return dashboardGet<AgentActivityEvent[]>(`/api/agents/activity?limit=${limit}`);
}

export async function getAgentMemories(agentName: string): Promise<AgentMemorySnapshot> {
  return dashboardGet<AgentMemorySnapshot>(`/api/agents/${encodeURIComponent(agentName)}/memories`);
}

export async function createSharedTask(agents: string[]): Promise<{ ok: boolean; task_id?: string; error?: string }> {
  return dashboardPost('/api/agents/shared-task', { agents });
}

export interface AutoRouteResult {
  ok: boolean;
  routed_to?: string[];
  result?: string;
  results?: Array<{ agent: string; status: string; result: string; confidence: number; error?: string }>;
  shared_task_id?: string | null;
  task_id?: string | null;
  error?: string;
}

export async function autoRouteTask(payload: {
  task: string;
  max_agents?: number;
  title?: string;
  success_criteria?: string;
  deliverables?: string[];
  workspace_path?: string;
  integration_targets?: string[];
  execution_mode?: string;
  require_approval?: boolean;
  approval_note?: string;
}): Promise<AutoRouteResult> {
  return dashboardPost('/api/agents/auto-route', payload);
}

export interface ConsensusResult {
  ok: boolean;
  result?: string;
  confidence?: number;
  agent_responses?: Array<{ agent: string; response: string; confidence: number }>;
  strategy?: string;
  error?: string;
}

export async function seekConsensus(payload: {
  task: string;
  agent_names: string[];
  strategy?: string;
  timeout_seconds?: number;
  title?: string;
  success_criteria?: string;
  deliverables?: string[];
  workspace_path?: string;
  integration_targets?: string[];
  execution_mode?: string;
  require_approval?: boolean;
  approval_note?: string;
}): Promise<ConsensusResult> {
  return dashboardPost('/api/agents/consensus', payload);
}

export interface PipelineStepResult {
  agent: string;
  status: string;
  result: string;
  confidence: number;
  elapsed_seconds: number;
  error?: string | null;
}

export interface PipelineResult {
  ok: boolean;
  status?: string;
  pipeline_results?: PipelineStepResult[];
  final_result?: string;
  shared_task_id?: string | null;
  task_id?: string | null;
  error?: string;
}

export async function pipelineTask(payload: {
  task: string;
  agent_names: string[];
  timeout_seconds?: number;
  title?: string;
  success_criteria?: string;
  deliverables?: string[];
  workspace_path?: string;
  integration_targets?: string[];
  execution_mode?: string;
  require_approval?: boolean;
  approval_note?: string;
}): Promise<PipelineResult> {
  return dashboardPost('/api/agents/pipeline', payload);
}

export async function getSharedTask(taskId: string): Promise<SharedTaskDetails> {
  return dashboardGet<SharedTaskDetails>(`/api/agents/shared-task/${encodeURIComponent(taskId)}`);
}

export async function delegateTask(
  agentName: string,
  task: string,
  options?: {
    agentNames?: string[];
    sharedTaskId?: string;
    title?: string;
    successCriteria?: string;
    deliverables?: string[];
    workspacePath?: string;
    integrationTargets?: string[];
    executionMode?: string;
    requireApproval?: boolean;
    approvalNote?: string;
  },
): Promise<{ ok: boolean; task_id?: string | null; child_task_ids?: string[]; status?: string; requested_model?: string | null; effective_model?: string | null; result?: string; error?: string; results?: Array<{ agent: string; status: string; result: string; confidence: number; error?: string; requested_model?: string; effective_model?: string }>; shared_task_id?: string | null }> {
  const body: Record<string, unknown> = { task };
  if (options?.agentNames?.length) body.agent_names = options.agentNames;
  else body.agent_name = agentName;
  if (options?.sharedTaskId) body.shared_task_id = options.sharedTaskId;
  if (options?.title) body.title = options.title;
  if (options?.successCriteria) body.success_criteria = options.successCriteria;
  if (options?.deliverables?.length) body.deliverables = options.deliverables;
  if (options?.workspacePath) body.workspace_path = options.workspacePath;
  if (options?.integrationTargets?.length) body.integration_targets = options.integrationTargets;
  if (options?.executionMode) body.execution_mode = options.executionMode;
  if (options?.requireApproval) body.require_approval = true;
  if (options?.approvalNote) body.approval_note = options.approvalNote;
  return dashboardPost('/api/agents/delegate', body);
}

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'partial' | 'awaiting_approval' | 'rejected' | string;

export interface TaskRecord {
  task_id: string;
  title: string;
  prompt: string;
  status: TaskStatus;
  provider: string;
  requested_model: string;
  effective_model: string;
  base_url: string;
  target_agents: string[];
  child_task_ids: string[];
  shared_task_id?: string | null;
  parent_task_id?: string | null;
  result: string;
  result_preview: string;
  error?: string | null;
  created_at: number;
  updated_at: number;
  started_at?: number | null;
  completed_at?: number | null;
  duration_ms?: number | null;
  metadata: Record<string, unknown>;
}

export interface TaskDetail extends TaskRecord {
  children: TaskRecord[];
}

export interface DesktopIntegration {
  id: string;
  label: string;
  category: string;
  enabled: boolean;
  connected: boolean;
  summary: string;
  details?: Record<string, unknown>;
}

export interface ModelHealthBadge {
  label: string;
  model: string;
  available: boolean;
  status: string;
}

export interface ModelHealthSnapshot {
  models: string[];
  resolved_base_url: string;
  available_count: number;
  last_seen?: number | null;
  badges: ModelHealthBadge[];
  fallback_chain: string[];
}

export async function getTasks(limit = 100): Promise<TaskRecord[]> {
  return dashboardGet<TaskRecord[]>(`/api/tasks?limit=${limit}`);
}

export async function getTask(taskId: string): Promise<TaskDetail> {
  return dashboardGet<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

export async function approveTask(taskId: string, payload: {
  note?: string;
  approved_by?: string;
} = {}): Promise<{ ok: boolean; task_id?: string; status?: string; message?: string; error?: string }> {
  return dashboardPost(`/api/tasks/${encodeURIComponent(taskId)}/approve`, payload);
}

export async function rejectTask(taskId: string, payload: {
  reason?: string;
} = {}): Promise<{ ok: boolean; task_id?: string; status?: string; message?: string; error?: string }> {
  return dashboardPost(`/api/tasks/${encodeURIComponent(taskId)}/reject`, payload);
}

export async function getDesktopIntegrations(): Promise<{ integrations: DesktopIntegration[]; count: number }> {
  return dashboardGet<{ integrations: DesktopIntegration[]; count: number }>('/api/integrations');
}

export interface IntegrationTestResponse {
  ok: boolean;
  message?: string;
  error?: string;
  details?: Record<string, unknown>;
}

export interface IntegrationConnectResponse {
  ok: boolean;
  auth_url?: string;
  message?: string;
  error?: string;
}

export interface AssistantScreenPreview {
  ok: boolean;
  monitor?: number;
  width?: number;
  height?: number;
  screenshot_b64?: string;
  data_url?: string;
  error?: string;
}

export async function testIntegration(
  integrationId: string,
  payload: Record<string, unknown> = {},
): Promise<IntegrationTestResponse> {
  return dashboardPost<IntegrationTestResponse>(`/api/integrations/${encodeURIComponent(integrationId)}/test`, payload);
}

export async function connectIntegration(
  integrationId: string,
  payload: Record<string, unknown> = {},
): Promise<IntegrationConnectResponse> {
  return dashboardPost<IntegrationConnectResponse>(`/api/integrations/${encodeURIComponent(integrationId)}/connect`, payload);
}

export async function disconnectIntegration(
  integrationId: string,
): Promise<{ ok: boolean; message?: string; error?: string }> {
  return dashboardPost(`/api/integrations/${encodeURIComponent(integrationId)}/disconnect`, {});
}

export async function getLocalModelHealth(): Promise<ModelHealthSnapshot> {
  return dashboardGet<ModelHealthSnapshot>('/api/models/local-health');
}

export async function captureAssistantScreen(payload: {
  monitor?: number;
} = {}): Promise<AssistantScreenPreview> {
  return dashboardPost<AssistantScreenPreview>('/api/assistant/screen', payload);
}

export interface OperatorBriefHighlight {
  id: string;
  label: string;
  value: number;
  tone: string;
  detail: string;
}

export interface OperatorBriefAction {
  id: string;
  title: string;
  summary: string;
  prompt: string;
  mode: string;
  integration_targets: string[];
  tone: string;
}

export interface OperatorBriefIntegrationContext {
  id: string;
  label: string;
  category: string;
  connected: boolean;
  health: string;
  detail: string;
  account?: string | null;
  recent_task_count: number;
  recent_action_count: number;
  latest_task?: {
    id?: string | null;
    title?: string | null;
    status?: string | null;
  } | null;
  next_prompt?: string | null;
}

export interface OperatorBrief {
  ok: boolean;
  generated_at: number;
  summary: {
    running_agents: number;
    connected_integrations: number;
    pending_approvals: number;
    failed_tasks: number;
    knowledge_documents: number;
    episodic_memories: number;
    semantic_memories: number;
    recent_audit_events: number;
    denied_actions: number;
  };
  highlights: OperatorBriefHighlight[];
  recent_task?: TaskRecord | null;
  recommended_actions: OperatorBriefAction[];
  integration_context?: OperatorBriefIntegrationContext[];
  connected_integrations: Array<{
    id: string;
    label: string;
    category: string;
    summary: string;
  }>;
  recent_actions?: AuditEvent[];
  adaptive_suggestions?: AdaptiveSuggestion[];
  next_actions?: AdaptiveSuggestion[];
  project_brief?: ProjectContextProfile;
  learning_diffs?: LearningDiff[];
  recent_receipts?: Array<ChangeReceipt & {
    snapshot_id?: string;
    resource_entries?: Array<{
      resource_type: string;
      target: string;
      rollback_kind: string;
      snapshot_supported?: boolean;
      rollback_status?: string;
      note?: string;
    }>;
    rollback_coverage?: {
      status: string;
      reversible_count: number;
      compensatable_count: number;
      irreversible_count: number;
      summary: string;
    };
  }>;
  proactive_routines?: ProactiveRoutine[];
  active_project?: {
    project_id?: string;
    status?: string;
    restored_skills?: string[];
    skill_snapshot?: string[];
  } | null;
  playbook_entries?: TeachingArtifact[];
  pending_reviews?: Array<Record<string, unknown>>;
}

export async function getOperatorBrief(): Promise<OperatorBrief> {
  return dashboardGet<OperatorBrief>('/api/operator/brief');
}

export async function reviewLearningDiff(cycleId: string, payload: {
  decision: 'approve' | 'reject' | 'probation';
  reviewer?: string;
  reason?: string;
}): Promise<{ ok: boolean; learning_diff?: Record<string, unknown>; error?: string }> {
  return dashboardPost(`/api/adaptive/reviews/${encodeURIComponent(cycleId)}`, payload);
}

export async function reviewRoutine(routineId: string, payload: {
  decision: 'approve' | 'reject' | 'probation';
  reason?: string;
}): Promise<{ ok: boolean; routine?: Record<string, unknown>; error?: string }> {
  return dashboardPost(`/api/adaptive/routines/${encodeURIComponent(routineId)}`, payload);
}

export async function activateProject(projectId: string): Promise<{ ok: boolean; project_id?: string; error?: string }> {
  return dashboardPost('/api/adaptive/projects/activate', { project_id: projectId });
}

export async function captureTeachingArtifact(payload: {
  source_id: string;
  title: string;
  transcript: string;
  task_prompt?: string;
  result_text?: string;
  tags?: string[];
}): Promise<{ ok: boolean; entry?: Record<string, unknown>; error?: string }> {
  return dashboardPost('/api/adaptive/teaching/capture', payload);
}

export async function getSkillGraph(): Promise<{ ok: boolean; graph: { nodes: Array<Record<string, unknown>>; edges: Array<Record<string, unknown>> } }> {
  return dashboardGet('/api/adaptive/skills/graph');
}

export async function createAdaptiveSnapshot(payload: {
  task_id?: string;
  file_paths: string[];
  metadata?: Record<string, unknown>;
}): Promise<{ ok: boolean; snapshot_id?: string; error?: string }> {
  return dashboardPost('/api/adaptive/snapshots', payload);
}

export async function executeAdaptiveRollback(payload: {
  receipt_id?: string;
  snapshot_id?: string;
}): Promise<{
  ok: boolean;
  rollback_id?: string;
  snapshot_id?: string;
  receipt_id?: string;
  status?: string;
  restored_paths?: string[];
  deleted_paths?: string[];
  skipped_paths?: Array<Record<string, unknown>>;
  error?: string;
}> {
  return dashboardPost('/api/adaptive/rollback', payload);
}

// ── Intent ──

export async function getIntentPredictions(limit = 10): Promise<{ ok: boolean; predictions: unknown[] }> {
  return dashboardGet(`/api/adaptive/intent/predictions?limit=${limit}`);
}

export async function getIntentStats(): Promise<{ ok: boolean; stats: Record<string, unknown> }> {
  return dashboardGet('/api/adaptive/intent/stats');
}

export async function observeIntent(action: string, context: Record<string, unknown> = {}): Promise<{ ok: boolean }> {
  return dashboardPost('/api/adaptive/intent/observe', { action, context });
}

// ── Style ──

export async function getStyleProfile(userId = 'default'): Promise<{ ok: boolean; profile: Record<string, unknown> }> {
  return dashboardGet(`/api/adaptive/style/profile?user_id=${userId}`);
}

export async function setStyleRule(key: string, value: string): Promise<{ ok: boolean }> {
  return dashboardPost('/api/adaptive/style/rule', { key, value });
}

// ── Compensating rollback ──

export async function getCompensatingHistory(limit = 20): Promise<{ ok: boolean; history: unknown[] }> {
  return dashboardGet(`/api/adaptive/compensating/history?limit=${limit}`);
}

export async function listCompensators(): Promise<{ ok: boolean; compensators: unknown[] }> {
  return dashboardGet('/api/adaptive/compensating/compensators');
}

export async function planCompensation(integration: string, action: string, payload: Record<string, unknown> = {}): Promise<{ ok: boolean; plan: unknown }> {
  return dashboardPost('/api/adaptive/compensating/plan', { integration, action, payload });
}

export async function executeCompensation(compensationId: string): Promise<{ ok: boolean; result: unknown }> {
  return dashboardPost('/api/adaptive/compensating/execute', { compensation_id: compensationId });
}

// ── Federation (adaptive) ──

export async function getFederatedSkills(): Promise<{ ok: boolean; skills: unknown[] }> {
  return dashboardGet('/api/adaptive/federation/skills');
}

export async function getFederationStats(): Promise<{ ok: boolean; stats: Record<string, unknown> }> {
  return dashboardGet('/api/adaptive/federation/stats');
}

export async function publishFederatedSkill(skillName: string, manifest: Record<string, unknown>): Promise<{ ok: boolean }> {
  return dashboardPost('/api/adaptive/federation/publish', { skill_name: skillName, manifest });
}

export async function importFederatedSkill(peerId: string, skillName: string): Promise<{ ok: boolean }> {
  return dashboardPost('/api/adaptive/federation/import', { peer_id: peerId, skill_name: skillName });
}

// ── Scheduler ──

export async function getSchedulerStatus(): Promise<{ ok: boolean; status: string }> {
  return dashboardGet('/api/adaptive/scheduler/status');
}

export async function forceRunRoutine(routineId: string): Promise<{ ok: boolean }> {
  return dashboardPost('/api/adaptive/scheduler/force', { routine_id: routineId });
}

export interface AuditEvent {
  timestamp: number;
  request_id: string;
  tool_name: string;
  action: string;
  allowed: boolean;
  success: boolean;
  denied_reason: string;
  result_preview: string;
  args_preview: string;
  execution_time_ms: number;
  platform?: string;
  channel_id?: string;
  user_id?: string;
  capabilities_used: string[];
}

export interface AuditStats {
  total_records: number;
  denied_records: number;
  denial_rate: number;
  top_tools: Array<[string, number]>;
  top_users: Array<[string, number]>;
}

export interface AuditTrailResponse {
  ok: boolean;
  events: AuditEvent[];
  stats: AuditStats;
}

export async function getAuditTrail(limit = 20): Promise<AuditTrailResponse> {
  return dashboardGet<AuditTrailResponse>(`/api/audit?limit=${limit}`);
}

// ── Types for chat (WebSocket-based, not REST) ──

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  confidence?: number;
  tool_calls?: ToolCall[];
  metadata?: Record<string, unknown>;
}

export interface ModelOption {
  name: string;
  description: string;
  icon: string;
  capabilities?: {
    supportsVision?: boolean;
    supportsDocuments?: boolean;
    supportsTools?: boolean;
  };
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result?: string;
  status?: 'running' | 'success' | 'error';
}

export interface DesktopChatSession {
  sessionId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  lastMessageAt: number;
  messageCount: number;
  preview: string;
  draft: string;
  metadata: ChatSessionMetadata;
}

export interface DesktopChatBootstrap {
  activeSessionId: string;
  sessions: DesktopChatSession[];
  messages: ChatMessage[];
  draft: string;
}

export interface DesktopChatSessionPayload {
  activeSessionId: string;
  messages: ChatMessage[];
  draft: string;
  metadata: ChatSessionMetadata;
}

export async function getChatBootstrap(): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('get_chat_bootstrap');
}

export async function createDesktopChatSession(title?: string): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('create_chat_session', { title });
}

export async function createDesktopChatSessionWithMetadata(
  title?: string,
  metadata?: ChatSessionMetadata,
): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('create_chat_session_with_metadata', { title, metadata });
}

export async function switchDesktopChatSession(sessionId: string): Promise<DesktopChatSessionPayload> {
  return invoke<DesktopChatSessionPayload>('switch_chat_session', { sessionId });
}

export async function renameDesktopChatSession(sessionId: string, title: string): Promise<DesktopChatSession[]> {
  return invoke<DesktopChatSession[]>('rename_chat_session', { sessionId, title });
}

export async function deleteDesktopChatSession(sessionId: string): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('delete_chat_session', { sessionId });
}

export async function clearDesktopChatSession(sessionId: string): Promise<DesktopChatSession[]> {
  return invoke<DesktopChatSession[]>('clear_chat_session', { sessionId });
}

export async function updateDesktopChatSessionMetadata(
  sessionId: string,
  metadata?: ChatSessionMetadata,
): Promise<DesktopChatSession[]> {
  return invoke<DesktopChatSession[]>('update_chat_session_metadata', { sessionId, metadata });
}

export async function resetAllDesktopChatSessions(): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('reset_all_chat_sessions');
}

export async function saveDesktopChatDraft(sessionId: string, content: string): Promise<void> {
  await invoke('save_chat_draft', { sessionId, content });
}

export async function saveDesktopChatMessage(sessionId: string, message: ChatMessage): Promise<DesktopChatSession[]> {
  return invoke<DesktopChatSession[]>('save_chat_message', { sessionId, message });
}

export async function ingestKnowledgeText(payload: {
  title: string;
  text?: string;
  source?: string;
  mimeType?: string;
  content?: string;
}): Promise<{ ok: boolean; error?: string; filename?: string; chunk_count?: number }> {
  const raw = await invoke<string>('ingest_kb_text', {
    title: payload.title,
    text: payload.text || '',
    source: payload.source,
    mimeType: payload.mimeType,
    content: payload.content,
  });
  return JSON.parse(raw) as { ok: boolean; error?: string; filename?: string; chunk_count?: number };
}

export interface KBDocument {
  id: string;
  filename: string;
  source: string;
  doc_type: string;
  ingested_at: number;
  chunk_count: number;
  metadata?: Record<string, unknown>;
}

export interface KBSearchResult {
  content: string;
  document: string;
  score: number;
  chunk_index: number;
}

export async function getKnowledgeDocuments(): Promise<KBDocument[]> {
  return dashboardGet<KBDocument[]>('/api/kb/documents');
}

export async function searchKnowledgeBase(query: string): Promise<KBSearchResult[]> {
  const result = await dashboardPost<{ results?: KBSearchResult[] }>('/api/kb/search', { query });
  return result.results || [];
}

export async function deleteKnowledgeDocument(documentId: string): Promise<{ ok: boolean }> {
  return dashboardDelete(`/api/kb/documents/${encodeURIComponent(documentId)}`);
}

export async function getProviderModels(
  provider: string,
  endpoint?: string,
  apiKey?: string,
): Promise<ModelOption[]> {
  // Try dashboard API first (works even without Tauri IPC)
  try {
    const params = new URLSearchParams();
    if (endpoint) params.set('endpoint', endpoint);
    if (apiKey) params.set('api_key', apiKey);
    const data = await dashboardGet(`/api/providers/${encodeURIComponent(provider)}/models?${params.toString()}`) as Record<string, unknown>;
    if (data.models && Array.isArray(data.models)) {
      return (data.models as Record<string, unknown>[]).map((m) => ({
        name: (m.id as string) || (m.name as string) || '',
        description: (m.description as string) || (m.parameter_size as string) || (m.family as string) || (m.owned_by as string) || '',
        icon: (m.supports_vision as boolean) ? 'IMG' : '',
        capabilities: {
          supportsVision: Boolean(m.supports_vision),
          supportsDocuments: Boolean(m.supports_documents ?? true),
          supportsTools: Boolean(m.supports_tools ?? true),
        },
      }));
    }
  } catch {
    // Fallback to Tauri IPC
  }
  const raw = await invoke<string>('list_provider_models', { provider, endpoint, apiKey });
  const parsed = JSON.parse(raw) as { models?: ModelOption[] };
  return parsed.models || [];
}

// ── Provider Status (Dashboard :8080/api/providers/status) ──

export interface ProviderStatus {
  name: string;
  endpoint: string;
  available: boolean;
  has_key: boolean;
  is_primary: boolean;
  configured: boolean;
}

export interface ProviderStatusResponse {
  providers: ProviderStatus[];
  primary: string;
}

export async function getProviderStatus(): Promise<ProviderStatusResponse> {
  return dashboardGet<ProviderStatusResponse>('/api/providers/status');
}


// ---------------------------------------------------------------------------
// Database BI
// ---------------------------------------------------------------------------

export interface DBConnection {
  name: string;
  driver: string;
  schema?: string;
  read_only: boolean;
  table_count: number;
  connected: boolean;
  persisted?: boolean;
  dsn_display?: string;
}

export interface DBQueryRoute {
  provider?: string;
  model?: string;
  base_url?: string;
  allow_fallback?: boolean;
}

export async function getDBConnections(): Promise<DBConnection[]> {
  return dashboardGet('/api/db/connections');
}

export async function connectDB(payload: {
  name: string;
  driver: string;
  dsn: string;
  schema?: string;
  read_only?: boolean;
}): Promise<{ ok: boolean; message: string }> {
  return dashboardPost('/api/db/connect', payload);
}

export async function disconnectDB(name: string): Promise<{ ok: boolean; message: string }> {
  return dashboardPost('/api/db/disconnect', { name });
}

export async function getDBTables(connection: string): Promise<{ ok: boolean; result: string }> {
  return dashboardGet(`/api/db/tables?connection=${encodeURIComponent(connection)}`);
}

export async function describeDBTable(connection: string, table: string): Promise<{ ok: boolean; result: string }> {
  return dashboardGet(`/api/db/describe/${encodeURIComponent(connection)}/${encodeURIComponent(table)}`);
}

export async function queryDB(connection: string, query: string): Promise<{ ok: boolean; result: string }> {
  return dashboardPost('/api/db/query', { connection, query });
}

export async function naturalQueryDB(
  connection: string,
  question: string,
  route?: DBQueryRoute,
): Promise<{ ok: boolean; result: string }> {
  return dashboardPost('/api/db/natural-query', { connection, question, ...(route || {}) });
}

export async function chartDB(payload: {
  connection: string;
  query: string;
  chart_type?: string;
  title?: string;
  x_column?: string;
  y_column?: string;
  group_column?: string;
  provider?: string;
  model?: string;
  base_url?: string;
  allow_fallback?: boolean;
}): Promise<{ ok: boolean; result: unknown }> {
  return dashboardPost('/api/db/chart', payload);
}

export async function explainDB(
  connection: string,
  question: string,
  route?: DBQueryRoute,
): Promise<{ ok: boolean; result: string }> {
  return dashboardPost('/api/db/explain', { connection, question, ...(route || {}) });
}
