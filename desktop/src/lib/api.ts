// NeuralClaw Desktop — API Client
// Maps to the actual Dashboard + WebChat backend routes

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
