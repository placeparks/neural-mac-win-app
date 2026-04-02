// NeuralClaw Desktop — API Client
// Maps to the actual Dashboard + WebChat backend routes

import { invoke } from '@tauri-apps/api/core';
import { DASHBOARD_BASE } from './constants';

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

async function dashboardGet<T = unknown>(path: string): Promise<T> {
  const resp = await fetch(`${DASHBOARD_BASE}${path}`);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json() as Promise<T>;
}

async function dashboardPost<T = unknown>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${DASHBOARD_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json() as Promise<T>;
}

async function dashboardDelete<T = unknown>(path: string): Promise<T> {
  const resp = await fetch(`${DASHBOARD_BASE}${path}`, { method: 'DELETE' });
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await readApiError(resp)}`);
  return resp.json() as Promise<T>;
}

// ── Health (Dashboard :8080/health) ──

export interface HealthResponse {
  status: string;
  version?: string;
  uptime?: string;
}

export async function getHealth(): Promise<HealthResponse> {
  return dashboardGet<HealthResponse>('/health');
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
}

export async function getMemoryStats(): Promise<MemoryStats> {
  return dashboardGet<MemoryStats>('/api/memory');
}

export async function clearMemory(): Promise<{ ok: boolean; episodic_deleted?: number; semantic_deleted?: number; procedural_deleted?: number }> {
  return dashboardPost('/api/memory/clear');
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
  media?: Array<Record<string, unknown>>;
  documents?: Array<Record<string, unknown>>;
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
  error?: string;
}

export async function sendChatMessage(payload: ChatSendPayload): Promise<ChatSendResponse> {
  return dashboardPost<ChatSendResponse>('/api/message', payload);
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
  type: string;
  source?: string;
  data_preview?: string;
  timestamp?: number;
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

export async function getProviderDefaults(provider: string): Promise<ProviderDefaults> {
  const parsed = await getConfig();
  const providers = (parsed.providers as Record<string, any> | undefined) || {};
  const section = (providers[provider] as Record<string, any> | undefined) || {};
  return {
    provider,
    primary: String(providers.primary || 'local'),
    baseUrl: String(section.base_url || ''),
    model: String(section.model || ''),
  };
}

export async function getPrimaryProviderDefaults(): Promise<ProviderDefaults> {
  const parsed = await getConfig();
  const providers = (parsed.providers as Record<string, any> | undefined) || {};
  const primary = String(providers.primary || 'local');
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
  running: boolean;
  trust_mode: string;
  token_present: boolean;
  restart_required: boolean;
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
}

export async function pairChannel(
  channelName: string,
  payload: Partial<ChannelUpdatePayload>,
): Promise<ChannelPairResponse> {
  return dashboardPost(`/api/channels/${encodeURIComponent(channelName)}/pair`, payload);
}

// ── Skills (Dashboard :8080/skills) ──

export async function getSkills(): Promise<unknown[]> {
  return dashboardGet('/skills');
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
  const resp = await fetch(`${DASHBOARD_BASE}/api/agents/definitions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(defn),
  });
  return resp.json();
}

export async function updateAgentDefinition(id: string, updates: Partial<AgentDefinition>): Promise<{ ok: boolean; error?: string }> {
  const resp = await fetch(`${DASHBOARD_BASE}/api/agents/definitions/${id}`, {
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

export async function getSharedTask(taskId: string): Promise<SharedTaskDetails> {
  return dashboardGet<SharedTaskDetails>(`/api/agents/shared-task/${encodeURIComponent(taskId)}`);
}

export async function delegateTask(
  agentName: string,
  task: string,
  options?: { agentNames?: string[]; sharedTaskId?: string },
): Promise<{ ok: boolean; task_id?: string | null; child_task_ids?: string[]; status?: string; requested_model?: string | null; effective_model?: string | null; result?: string; error?: string; results?: Array<{ agent: string; status: string; result: string; confidence: number; error?: string; requested_model?: string; effective_model?: string }>; shared_task_id?: string | null }> {
  const body: Record<string, unknown> = { task };
  if (options?.agentNames?.length) body.agent_names = options.agentNames;
  else body.agent_name = agentName;
  if (options?.sharedTaskId) body.shared_task_id = options.sharedTaskId;
  return dashboardPost('/api/agents/delegate', body);
}

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'partial' | string;

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

export async function getLocalModelHealth(): Promise<ModelHealthSnapshot> {
  return dashboardGet<ModelHealthSnapshot>('/api/models/local-health');
}

// ── Types for chat (WebSocket-based, not REST) ──

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  confidence?: number;
  tool_calls?: ToolCall[];
}

export interface ModelOption {
  name: string;
  description: string;
  icon: string;
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
  const raw = await invoke<string>('list_provider_models', { provider, endpoint, apiKey });
  const parsed = JSON.parse(raw) as { models?: ModelOption[] };
  return parsed.models || [];
}
