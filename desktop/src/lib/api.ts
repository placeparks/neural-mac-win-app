// NeuralClaw Desktop — API Client
// Maps to the actual Dashboard + WebChat backend routes

import { invoke } from '@tauri-apps/api/core';
import { DASHBOARD_BASE } from './constants';

async function dashboardGet<T = unknown>(path: string): Promise<T> {
  const resp = await fetch(`${DASHBOARD_BASE}${path}`);
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await resp.text().catch(() => 'Unknown')}`);
  return resp.json() as Promise<T>;
}

async function dashboardPost<T = unknown>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${DASHBOARD_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await resp.text().catch(() => 'Unknown')}`);
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
  memory_namespace?: string;
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
  return dashboardPost('/api/agents/definitions', defn);
}

export async function updateAgentDefinition(id: string, updates: Partial<AgentDefinition>): Promise<{ ok: boolean }> {
  const resp = await fetch(`${DASHBOARD_BASE}/api/agents/definitions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  return resp.json();
}

export async function deleteAgentDefinition(id: string): Promise<{ ok: boolean }> {
  const resp = await fetch(`${DASHBOARD_BASE}/api/agents/definitions/${id}`, { method: 'DELETE' });
  return resp.json();
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
): Promise<{ ok: boolean; result?: string; error?: string; results?: Array<{ agent: string; status: string; result: string; confidence: number; error?: string }>; shared_task_id?: string | null }> {
  const body: Record<string, unknown> = { task };
  if (options?.agentNames?.length) body.agent_names = options.agentNames;
  else body.agent_name = agentName;
  if (options?.sharedTaskId) body.shared_task_id = options.sharedTaskId;
  return dashboardPost('/api/agents/delegate', body);
}

// ── Types for chat (WebSocket-based, not REST) ──

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  confidence?: number;
  tool_calls?: ToolCall[];
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
}

export async function getChatBootstrap(): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('get_chat_bootstrap');
}

export async function createDesktopChatSession(title?: string): Promise<DesktopChatBootstrap> {
  return invoke<DesktopChatBootstrap>('create_chat_session', { title });
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

export async function saveDesktopChatDraft(sessionId: string, content: string): Promise<void> {
  await invoke('save_chat_draft', { sessionId, content });
}

export async function saveDesktopChatMessage(sessionId: string, message: ChatMessage): Promise<DesktopChatSession[]> {
  return invoke<DesktopChatSession[]>('save_chat_message', { sessionId, message });
}
