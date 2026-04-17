// NeuralClaw Desktop — Dashboard Page
// Uses IPC commands for reliability

import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { DASHBOARD_BASE } from '../lib/constants';
import { PROVIDER_COLORS, type ProviderId } from '../lib/theme';
import {
  activateProject,
  autoRouteTask,
  createAdaptiveSnapshot,
  executeAdaptiveRollback,
  getBackendRuntimeStatus,
  getSkillGraph,
  getAuditTrail,
  getOperatorBrief,
  getProviderStatus,
  reviewLearningDiff,
  reviewRoutine,
  getIntentPredictions,
  getIntentStats,
  observeIntent,
  getStyleProfile,
  setStyleRule,
  getCompensatingHistory,
  listCompensators,
  executeCompensation,
  getFederatedSkills,
  getFederationStats,
  getBusEvents,
  getSchedulerStatus,
  forceRunRoutine,
  type AuditTrailResponse,
  type OperatorBrief,
  type ProviderStatus,
} from '../lib/api';
import { wsManager } from '../lib/ws';
import { useAppStore } from '../store/appStore';

interface Stats {
  provider?: string;
  active_provider?: string;
  configured_primary_provider?: string;
  active_model?: string;
  active_base_url?: string;
  interactions?: number;
  success_rate?: number;
  skills?: number;
  channels?: string;
  uptime?: string;
  readiness?: string;
  event_count?: number;
  trace_available?: boolean;
  adaptive_ready?: boolean;
  operator_ready?: boolean;
}

interface Trace {
  trace_id?: string;
  category: string;
  message: string;
  timestamp: number;
  reasoning_path?: string;
  input_preview?: string;
  output_preview?: string;
  total_tool_calls?: number;
  duration_ms?: number;
  confidence?: number;
  error?: string | null;
}

interface BusEvent {
  id?: string;
  type: string;
  source?: string;
  data_preview?: string;
  timestamp?: number;
  correlation_id?: string | null;
  level?: 'info' | 'success' | 'warning' | 'error';
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [health, setHealth] = useState<{ status: string; version?: string; uptime?: string } | null>(null);
  const [runtime, setRuntime] = useState<Record<string, any> | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [brief, setBrief] = useState<OperatorBrief | null>(null);
  const [audit, setAudit] = useState<AuditTrailResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [launchingActionId, setLaunchingActionId] = useState<string | null>(null);
  const [skillGraphCounts, setSkillGraphCounts] = useState<{ nodes: number; edges: number }>({ nodes: 0, edges: 0 });
  const [intentPredictions, setIntentPredictions] = useState<unknown[]>([]);
  const [intentStats, setIntentStats] = useState<Record<string, unknown> | null>(null);
  const [styleProfile, setStyleProfile] = useState<Record<string, unknown> | null>(null);
  const [styleRuleKey, setStyleRuleKey] = useState('');
  const [styleRuleValue, setStyleRuleValue] = useState('');
  const [compensatingHistory, setCompensatingHistory] = useState<unknown[]>([]);
  const [compensators, setCompensators] = useState<unknown[]>([]);
  const [federatedSkills, setFederatedSkills] = useState<unknown[]>([]);
  const [federationStats, setFederationStats] = useState<Record<string, unknown> | null>(null);
  const [schedulerStatus, setSchedulerStatus] = useState<string | null>(null);
  const [wave2Loading, setWave2Loading] = useState(false);
  const pushToast = useAppStore((state) => state.pushToast);
  const primaryProvider = providers.find((provider) => provider.is_primary) || null;
  const runtimeRouteLabel = stats?.active_provider || stats?.provider || 'unresolved';
  const configuredPrimaryLabel = stats?.configured_primary_provider || primaryProvider?.name || 'unconfigured';
  const runtimePhase = runtime?.readiness_phase || stats?.readiness || 'unknown';
  const observabilityHealthy = Boolean(stats?.trace_available && stats?.event_count !== undefined);
  const runtimePhaseLabel = String(runtimePhase).split('_').join(' ');

  const renderTraceSummary = useCallback((trace: Trace) => {
    if (trace.output_preview) return trace.output_preview;
    if (trace.input_preview) return trace.input_preview;
    return trace.message;
  }, []);

  const loadAll = useCallback(async () => {
    setRefreshing(true);
    const results = await Promise.allSettled([
      invoke<string>('get_health'),
      invoke<string>('get_dashboard_stats'),
      getBackendRuntimeStatus(),
      getOperatorBrief(),
      getAuditTrail(12),
    ]);

    if (results[0].status === 'fulfilled') {
      try { setHealth(JSON.parse(results[0].value)); } catch { /* */ }
    }
    if (results[1].status === 'fulfilled') {
      try { setStats(JSON.parse(results[1].value)); } catch { /* */ }
    }
    if (results[2].status === 'fulfilled') {
      setRuntime(results[2].value);
    }
    if (results[3].status === 'fulfilled') {
      setBrief(results[3].value);
    }
    if (results[4].status === 'fulfilled') {
      setAudit(results[4].value);
    }

    // Try traces and bus events (may not exist)
    try {
      const resp = await fetch(`${DASHBOARD_BASE}/api/traces?limit=20`);
      if (resp.ok) setTraces(await resp.json());
    } catch { /* */ }

    try {
      setEvents(await getBusEvents());
    } catch { /* */ }

    // Load provider status
    try {
      const status = await getProviderStatus();
      setProviders(status.providers);
    } catch { /* */ }

    try {
      const graph = await getSkillGraph();
      setSkillGraphCounts({
        nodes: graph.graph?.nodes?.length || 0,
        edges: graph.graph?.edges?.length || 0,
      });
    } catch { /* */ }

    // Wave-2 data
    setWave2Loading(true);
    const wave2 = await Promise.allSettled([
      getIntentPredictions(10),
      getIntentStats(),
      getStyleProfile(),
      getCompensatingHistory(20),
      listCompensators(),
      getFederatedSkills(),
      getFederationStats(),
      getSchedulerStatus(),
    ]);
    if (wave2[0].status === 'fulfilled') setIntentPredictions(wave2[0].value.predictions || []);
    if (wave2[1].status === 'fulfilled') setIntentStats(wave2[1].value.stats || null);
    if (wave2[2].status === 'fulfilled') setStyleProfile(wave2[2].value.profile || null);
    if (wave2[3].status === 'fulfilled') setCompensatingHistory(wave2[3].value.history || []);
    if (wave2[4].status === 'fulfilled') setCompensators(wave2[4].value.compensators || []);
    if (wave2[5].status === 'fulfilled') setFederatedSkills(wave2[5].value.skills || []);
    if (wave2[6].status === 'fulfilled') setFederationStats(wave2[6].value.stats || null);
    if (wave2[7].status === 'fulfilled') setSchedulerStatus(wave2[7].value.status || null);
    setWave2Loading(false);

    setRefreshing(false);
  }, []);

  const runRecommendedAction = useCallback(async (action: NonNullable<OperatorBrief['recommended_actions']>[number]) => {
    setLaunchingActionId(action.id);
    try {
      const response = await autoRouteTask({
        task: action.prompt,
        title: action.title,
        integration_targets: action.integration_targets,
        execution_mode: 'integration-loop',
      });
      if (!response.ok) {
        throw new Error(response.error || 'Action failed');
      }
      pushToast({
        title: 'Agent workflow started',
        description: response.task_id
          ? `${action.title} is now tracked as task ${response.task_id}.`
          : `${action.title} has been handed to the agents.`,
        level: 'success',
      });
      if (response.task_id) {
        window.dispatchEvent(new CustomEvent('neuralclaw:navigate', { detail: 'tasks' }));
      }
      await loadAll();
    } catch (error: any) {
      pushToast({
        title: 'Failed to launch action',
        description: error?.message || `Could not launch ${action.title}.`,
        level: 'error',
      });
    } finally {
      setLaunchingActionId(null);
    }
  }, [loadAll, pushToast]);

  const applyLearningDecision = useCallback(async (cycleId: string, decision: 'approve' | 'reject' | 'probation') => {
    const result = await reviewLearningDiff(cycleId, { decision });
    pushToast({
      title: result.ok ? 'Learning review updated' : 'Review update failed',
      description: result.ok ? `${cycleId} -> ${decision}` : (result.error || 'Unable to update review.'),
      level: result.ok ? 'success' : 'error',
    });
    await loadAll();
  }, [loadAll, pushToast]);

  const applyRoutineDecision = useCallback(async (routineId: string, decision: 'approve' | 'reject' | 'probation') => {
    const result = await reviewRoutine(routineId, { decision });
    pushToast({
      title: result.ok ? 'Routine updated' : 'Routine update failed',
      description: result.ok ? `${routineId} -> ${decision}` : (result.error || 'Unable to update routine.'),
      level: result.ok ? 'success' : 'error',
    });
    await loadAll();
  }, [loadAll, pushToast]);

  const activateProjectContext = useCallback(async (projectId: string) => {
    const result = await activateProject(projectId);
    pushToast({
      title: result.ok ? 'Project activated' : 'Project activation failed',
      description: result.ok ? projectId : (result.error || 'Unable to activate project.'),
      level: result.ok ? 'success' : 'error',
    });
    await loadAll();
  }, [loadAll, pushToast]);

  const captureReceiptSnapshot = useCallback(async (taskId: string, filePaths: string[]) => {
    const result = await createAdaptiveSnapshot({
      task_id: taskId,
      file_paths: filePaths,
      metadata: { source: 'dashboard_receipt' },
    });
    pushToast({
      title: result.ok ? 'Snapshot captured' : 'Snapshot failed',
      description: result.ok ? (result.snapshot_id || taskId) : (result.error || 'Unable to capture snapshot.'),
      level: result.ok ? 'success' : 'error',
    });
    await loadAll();
  }, [loadAll, pushToast]);

  const rollbackReceipt = useCallback(async (receiptId: string) => {
    const result = await executeAdaptiveRollback({ receipt_id: receiptId });
    pushToast({
      title: result.ok ? 'Rollback completed' : 'Rollback failed',
      description: result.ok
        ? `${result.restored_paths?.length || 0} restored, ${result.deleted_paths?.length || 0} removed`
        : (result.error || 'Unable to execute rollback.'),
      level: result.ok ? 'success' : 'error',
    });
    await loadAll();
  }, [loadAll, pushToast]);

  useEffect(() => { loadAll(); }, [loadAll]);

  useEffect(() => {
    const unsubBus = wsManager.on('bus', (event) => {
      if (Array.isArray(event.data)) {
        setEvents(event.data as BusEvent[]);
      }
    });
    return () => unsubBus();
  }, []);

  // Auto-refresh every 10s
  useEffect(() => {
    const timer = setInterval(loadAll, 10000);
    return () => clearInterval(timer);
  }, [loadAll]);

  return (
    <>
      <Header title="Dashboard" />
      <div className="app-content">
        <div className="page-header">
          <h1>📊 Dashboard</h1>
          <p>Real-time statistics, agent activity, and system health.</p>
        </div>

        <div className="page-body">
          <section className="dashboard-command-deck">
            <div>
              <div className="eyebrow">Operator Surface</div>
              <h2>Runtime truth, adaptive signals, and execution trust rails</h2>
              <p>
                Use this page to see what the backend is actually doing, which providers are alive, and what the adaptive layer thinks should happen next.
              </p>
            </div>
            <div className="dashboard-command-stats">
              <div className="dashboard-command-stat">
                <span>Health</span>
                <strong>{health?.status || 'unknown'}</strong>
              </div>
              <div className="dashboard-command-stat">
                <span>Providers</span>
                <strong>{providers.length}</strong>
              </div>
              <div className="dashboard-command-stat">
                <span>Skill graph</span>
                <strong>{skillGraphCounts.nodes} nodes</strong>
              </div>
            </div>
          </section>

          <div className="info-box" style={{ marginBottom: 16 }}>
            <span className="info-icon">i</span>
            <span>
              Dashboard separates runtime truth from provider inventory. The runtime route below shows what the backend is actually executing through right now; provider inventory only shows what is configured or available for switching and fallback.
            </span>
          </div>

          <div className="workspace-guide-grid" style={{ marginBottom: 20 }}>
            <div className="workspace-guide-card">
              <div className="workspace-guide-title">Runtime Truth</div>
              <p>Trust runtime route, readiness phase, and operator readiness first. Do not infer execution path from whichever provider card is marked primary.</p>
            </div>
            <div className="workspace-guide-card">
              <div className="workspace-guide-title">Observability</div>
              <p>Recent traces show execution summaries; Event Bus shows system activity. If traces are empty but work is happening, that is an observability issue, not a reason to guess.</p>
            </div>
            <div className="workspace-guide-card">
              <div className="workspace-guide-title">Escalate Precisely</div>
              <p>Use audit trail for policy and tool decisions, traces for execution path, and runtime phase for startup diagnosis. Each surface answers a different question.</p>
            </div>
          </div>

          {brief && (
            <div className="operator-brief-shell">
              <div className="operator-brief-hero">
                <div>
                  <div className="operator-brief-eyebrow">Operator Brief</div>
                  <h2>What needs attention now</h2>
                  <p>
                    Context from recent task execution, connected integrations, and indexed workspace memory.
                  </p>
                </div>
                <div className="operator-brief-stats">
                  <div className="operator-mini-stat">
                    <span className="operator-mini-label">Agents</span>
                    <strong>{brief.summary.running_agents}</strong>
                  </div>
                  <div className="operator-mini-stat">
                    <span className="operator-mini-label">Approvals</span>
                    <strong>{brief.summary.pending_approvals}</strong>
                  </div>
                  <div className="operator-mini-stat">
                    <span className="operator-mini-label">Integrations</span>
                    <strong>{brief.summary.connected_integrations}</strong>
                  </div>
                </div>
              </div>

              <div className="operator-highlight-grid">
                {brief.highlights.map((item) => (
                  <div key={item.id} className={`operator-highlight-card tone-${item.tone}`}>
                    <div className="operator-highlight-label">{item.label}</div>
                    <div className="operator-highlight-value">{item.value}</div>
                    <div className="operator-highlight-detail">{item.detail}</div>
                  </div>
                ))}
              </div>

              <div className="operator-brief-grid">
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Recommended Actions</h3>
                    <span>{brief.recommended_actions.length} ready</span>
                  </div>
                  <div className="info-box" style={{ marginBottom: 12 }}>
                    <span className="info-icon">i</span>
                    <span>
                      These actions are generated from recent tasks, approvals, integrations, and memory context. Run one when you want agents to act immediately without manually composing the whole delegation brief.
                    </span>
                  </div>
                  <div className="operator-action-list">
                    {brief.recommended_actions.map((action) => (
                      <div key={action.id} className={`operator-action-card tone-${action.tone}`}>
                        <div className="operator-action-top">
                          <div>
                            <div className="operator-action-title">{action.title}</div>
                            <div className="operator-action-summary">{action.summary}</div>
                          </div>
                          {action.integration_targets.length > 0 ? (
                            <div className="task-detail-chips">
                              {action.integration_targets.map((target) => (
                                <span key={target} className="badge">{target}</span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                        <pre className="operator-action-prompt">{action.prompt}</pre>
                        <div className="operator-action-footer">
                          <button
                            className="btn btn-primary"
                            disabled={launchingActionId === action.id}
                            onClick={() => { void runRecommendedAction(action); }}
                          >
                            {launchingActionId === action.id ? 'Launching...' : 'Run With Agents'}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Context Snapshot</h3>
                    <span>{brief.connected_integrations.length} connected apps</span>
                  </div>
                  <div className="info-box" style={{ marginBottom: 12 }}>
                    <span className="info-icon">i</span>
                    <span>
                      Treat this as the assistant’s current working memory summary. If it looks thin or wrong, improve connections, memory, or recent task execution rather than forcing the model to guess from scratch.
                    </span>
                  </div>
                  {brief.recent_task ? (
                    <div className="operator-context-card">
                      <div className="operator-context-label">Latest task</div>
                      <div className="operator-context-title">{brief.recent_task.title}</div>
                      <div className="operator-context-meta">
                        <span className="badge">{brief.recent_task.status}</span>
                        <span>{brief.recent_task.effective_model || brief.recent_task.requested_model || 'auto'}</span>
                      </div>
                      <div className="operator-context-body">{brief.recent_task.result_preview || brief.recent_task.prompt}</div>
                    </div>
                  ) : (
                    <div className="empty-state" style={{ padding: 20 }}>
                      <span className="empty-icon">OP</span>
                      <h3>No recent task context</h3>
                      <p>Agent work launched from Tasks and Dashboard will show up here.</p>
                    </div>
                  )}

                  <div className="operator-context-stack">
                    <div className="operator-context-block">
                      <div className="operator-context-label">Connected integrations</div>
                      <div className="task-detail-chips">
                        {brief.connected_integrations.length > 0 ? brief.connected_integrations.map((item) => (
                          <span key={item.id} className="badge">{item.label}</span>
                        )) : <span className="badge">None connected</span>}
                      </div>
                    </div>
                    <div className="operator-context-block">
                      <div className="operator-context-label">Memory health</div>
                      <div className="operator-context-body">
                        Episodic: {brief.summary.episodic_memories} · Semantic: {brief.summary.semantic_memories} · Knowledge docs: {brief.summary.knowledge_documents}
                      </div>
                    </div>
                    {brief.integration_context && brief.integration_context.length > 0 ? (
                      <div className="operator-context-block">
                        <div className="operator-context-label">Integration activity</div>
                        <div className="task-child-list">
                          {brief.integration_context.map((item) => (
                            <div key={item.id} className="task-child-card">
                              <div className="task-child-top">
                                <span>{item.label}</span>
                                <span className={`badge badge-${item.health === 'healthy' ? 'green' : item.health === 'idle' ? 'blue' : 'orange'}`}>
                                  {item.health}
                                </span>
                              </div>
                              <div className="task-child-preview">
                                {item.detail}
                                {item.account ? ` Account: ${item.account}.` : ''}
                              </div>
                              <div className="task-child-meta">
                                <span>{item.recent_task_count} tasks</span>
                                <span>{item.recent_action_count} actions</span>
                                {item.latest_task?.status ? <span>{item.latest_task.status}</span> : null}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </section>
              </div>

              <div className="operator-brief-grid" style={{ marginTop: 16 }}>
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Next Actions</h3>
                    <span>{brief.adaptive_suggestions?.length || 0} adaptive</span>
                  </div>
                  <div className="task-child-list">
                    {(brief.adaptive_suggestions || []).map((item) => (
                      <div key={item.suggestion_id} className="task-child-card">
                        <div className="task-child-top">
                          <span>{item.title}</span>
                          <span className={`badge badge-${item.requires_approval ? 'orange' : 'green'}`}>
                            {Math.round(item.confidence * 100)}%
                          </span>
                        </div>
                        <div className="task-child-preview">{item.summary}</div>
                        <div className="task-child-meta">
                          <span>{item.category}</span>
                          <span>{item.risk_level}</span>
                        </div>
                        <div className="operator-context-body" style={{ marginTop: 8 }}>
                          {item.proposed_action}
                        </div>
                      </div>
                    ))}
                    {(!brief.adaptive_suggestions || brief.adaptive_suggestions.length === 0) ? (
                      <div className="empty-state" style={{ padding: 20 }}>
                        <span className="empty-icon">AI</span>
                        <h3>No adaptive suggestions yet</h3>
                        <p>Run more tasks or connect more context to feed the adaptive layer.</p>
                      </div>
                    ) : null}
                  </div>
                </section>

                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Project Brief</h3>
                    <span>{brief.project_brief?.title || 'workspace'}</span>
                  </div>
                  <div className="task-child-list">
                    <div className="task-child-card">
                      <div className="task-child-top">
                        <span>Workspace context</span>
                    <span className="badge">{brief.active_project?.project_id === brief.project_brief?.project_id ? 'active' : (brief.project_brief?.preferred_provider || 'primary')}</span>
                      </div>
                      <div className="task-child-preview">{brief.project_brief?.agents_md_summary || 'No project summary available.'}</div>
                      {brief.project_brief?.project_id ? (
                        <div className="task-detail-actions" style={{ marginTop: 12 }}>
                          <button className="btn btn-secondary" onClick={() => { void activateProjectContext(String(brief.project_brief?.project_id)); }}>
                            Activate Project
                          </button>
                        </div>
                      ) : null}
                    </div>
                    {(brief.project_brief?.last_known_open_work || []).map((item, index) => (
                      <div key={`${index}-${item}`} className="task-child-card">
                        <div className="task-child-top"><span>Open work</span></div>
                        <div className="task-child-preview">{item}</div>
                      </div>
                    ))}
                    {(brief.project_brief?.active_skills || []).length > 0 ? (
                      <div className="task-child-card">
                        <div className="task-child-top"><span>Active skills</span></div>
                        <div className="task-child-preview">{(brief.project_brief?.active_skills || []).join(', ')}</div>
                      </div>
                    ) : null}
                  </div>
                </section>
              </div>

              <div className="operator-brief-grid" style={{ marginTop: 16 }}>
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Learning Review</h3>
                    <span>{brief.learning_diffs?.length || 0} changes</span>
                  </div>
                  <div className="task-child-list">
                    {(brief.learning_diffs || []).map((item) => (
                      <div key={item.cycle_id} className="task-child-card">
                        <div className="task-child-top">
                          <span>{item.probation_status}</span>
                          <span className="badge">{item.approval_status}</span>
                        </div>
                        <div className="task-child-preview">{item.behavior_change_summary}</div>
                        {item.last_error ? (
                          <div className="task-child-meta">
                            <span>{item.last_error}</span>
                          </div>
                        ) : null}
                        <div className="task-detail-actions" style={{ marginTop: 12 }}>
                          <button className="btn btn-secondary" onClick={() => { void applyLearningDecision(item.cycle_id, 'approve'); }}>Approve</button>
                          <button className="btn btn-secondary" onClick={() => { void applyLearningDecision(item.cycle_id, 'probation'); }}>Probation</button>
                          <button className="btn btn-secondary" onClick={() => { void applyLearningDecision(item.cycle_id, 'reject'); }}>Reject</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Change Receipts</h3>
                    <span>{brief.recent_receipts?.length || 0} recent</span>
                  </div>
                  <div className="task-child-list">
                    {(brief.recent_receipts || []).map((item) => (
                      <div key={item.receipt_id} className="task-child-card">
                        {(() => {
                          const hasRollback = Boolean(item.rollback_available || item.snapshot_id);
                          const wasRolledBack = Boolean(item.rollback_token);
                          return (
                            <>
                        <div className="task-child-top">
                          <span>{item.task_id || item.receipt_id}</span>
                          <span className={`badge ${wasRolledBack ? 'badge-green' : hasRollback ? 'badge-orange' : 'badge-blue'}`}>
                            {wasRolledBack ? 'rolled-back' : hasRollback ? 'snapshot-ready' : 'receipt'}
                          </span>
                        </div>
                        <div className="task-child-preview">{item.operations.join(', ') || 'No operations captured.'}</div>
                        {item.files_changed.length > 0 ? (
                          <div className="task-child-meta">
                            <span>{item.files_changed.join(', ')}</span>
                          </div>
                        ) : null}
                        {item.rollback_coverage ? (
                          <div className="task-child-meta">
                            <span>{item.rollback_coverage.summary}</span>
                          </div>
                        ) : null}
                        {Array.isArray(item.resource_entries) && item.resource_entries.length > 0 ? (
                          <div className="task-child-meta">
                            <span>{item.resource_entries.map((entry) => `${entry.resource_type}:${entry.rollback_kind}`).join(' · ')}</span>
                          </div>
                        ) : null}
                        <div className="task-detail-actions" style={{ marginTop: 12 }}>
                          <button
                            className="btn btn-secondary"
                            onClick={() => { void captureReceiptSnapshot(String(item.task_id || item.receipt_id), item.files_changed); }}
                            disabled={item.files_changed.length === 0}
                          >
                            Capture snapshot
                          </button>
                          <button
                            className="btn btn-secondary"
                            onClick={() => { void rollbackReceipt(item.receipt_id); }}
                            disabled={!hasRollback}
                          >
                            Roll back
                          </button>
                        </div>
                            </>
                          );
                        })()}
                      </div>
                    ))}
                  </div>
                </section>
              </div>

              <div className="operator-brief-grid" style={{ marginTop: 16 }}>
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Proactive Routines</h3>
                    <span>{brief.proactive_routines?.length || 0} tracked</span>
                  </div>
                  <div className="task-child-list">
                    {(brief.proactive_routines || []).map((item) => (
                      <div key={String(item.routine_id)} className="task-child-card">
                        <div className="task-child-top">
                          <span>{String(item.title || item.name || item.routine_id)}</span>
                          <span className="badge">{String(item.probation_status || item.state || 'observed')}</span>
                        </div>
                        <div className="task-child-preview">{String(item.action_template || item.proposed_workflow || item.trigger_pattern || '')}</div>
                        <div className="task-detail-actions" style={{ marginTop: 12 }}>
                          <button className="btn btn-secondary" onClick={() => { void applyRoutineDecision(String(item.routine_id), 'approve'); }}>Promote</button>
                          <button className="btn btn-secondary" onClick={() => { void applyRoutineDecision(String(item.routine_id), 'probation'); }}>Probation</button>
                          <button className="btn btn-secondary" onClick={() => { void applyRoutineDecision(String(item.routine_id), 'reject'); }}>Quarantine</button>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Playbook & Graph</h3>
                    <span>{skillGraphCounts.nodes} skills / {skillGraphCounts.edges} links</span>
                  </div>
                  <div className="task-child-list">
                    {(brief.playbook_entries || []).map((item) => (
                      <div key={item.entry_id} className="task-child-card">
                        <div className="task-child-top">
                          <span>{item.title}</span>
                          <span className="badge">{(item.tags || []).slice(0, 1)[0] || 'playbook'}</span>
                        </div>
                        <div className="task-child-preview">{item.template_candidate || item.transcript || 'No transcript.'}</div>
                      </div>
                    ))}
                    {(!brief.playbook_entries || brief.playbook_entries.length === 0) ? (
                      <div className="task-child-card">
                        <div className="task-child-top"><span>Teaching mode</span></div>
                        <div className="task-child-preview">Run chats or tasks with teaching mode enabled to populate reusable playbook entries and skill candidates.</div>
                      </div>
                    ) : null}
                  </div>
                </section>
              </div>

              {/* Wave-2 Panels */}
              <div className="operator-brief-grid" style={{ marginTop: 16 }}>
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Intent Predictions</h3>
                    <span>{intentPredictions.length} predictions</span>
                  </div>
                  {wave2Loading ? (
                    <div className="empty-state" style={{ padding: 20 }}>
                      <span className="spinner" style={{ width: 18, height: 18 }} />
                      <p>Loading intent data...</p>
                    </div>
                  ) : (
                    <div className="task-child-list">
                      {intentStats && (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Stats</span>
                            <span className="badge badge-blue">overview</span>
                          </div>
                          <div className="task-child-preview">
                            {Object.entries(intentStats).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ')}
                          </div>
                        </div>
                      )}
                      {intentPredictions.map((pred: any, idx: number) => (
                        <div key={pred?.id || idx} className="task-child-card">
                          <div className="task-child-top">
                            <span>{pred?.action || pred?.intent || `Prediction ${idx + 1}`}</span>
                            <span className={`badge ${(pred?.confidence ?? 0) > 0.7 ? 'badge-green' : 'badge-orange'}`}>
                              {pred?.confidence != null ? `${Math.round(pred.confidence * 100)}%` : '?'}
                            </span>
                          </div>
                          <div className="task-child-preview">{pred?.context ? JSON.stringify(pred.context) : 'No context'}</div>
                        </div>
                      ))}
                      {intentPredictions.length === 0 && !intentStats && (
                        <div className="empty-state" style={{ padding: 20 }}>
                          <span className="empty-icon">INT</span>
                          <h3>No intent predictions</h3>
                          <p>Use the system more to generate intent predictions.</p>
                        </div>
                      )}
                      <div className="task-detail-actions" style={{ marginTop: 12 }}>
                        <button className="btn btn-secondary" onClick={() => { void observeIntent('dashboard_view', { source: 'dashboard' }).then(loadAll); }}>
                          Observe current intent
                        </button>
                      </div>
                    </div>
                  )}
                </section>

                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Style Profile</h3>
                    <span>{styleProfile ? 'loaded' : 'pending'}</span>
                  </div>
                  {wave2Loading ? (
                    <div className="empty-state" style={{ padding: 20 }}>
                      <span className="spinner" style={{ width: 18, height: 18 }} />
                      <p>Loading style profile...</p>
                    </div>
                  ) : (
                    <div className="task-child-list">
                      {styleProfile ? (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Current Profile</span>
                            <span className="badge badge-blue">active</span>
                          </div>
                          <div className="task-child-preview">
                            {Object.entries(styleProfile).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ')}
                          </div>
                        </div>
                      ) : (
                        <div className="empty-state" style={{ padding: 20 }}>
                          <span className="empty-icon">STY</span>
                          <h3>No style profile</h3>
                          <p>Style profile data will appear once the backend provides it.</p>
                        </div>
                      )}
                      <div className="task-child-card">
                        <div className="task-child-top"><span>Set Style Rule</span></div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                          <input
                            className="input"
                            placeholder="Key (e.g. tone)"
                            value={styleRuleKey}
                            onChange={(e) => setStyleRuleKey(e.target.value)}
                            style={{ flex: 1, minWidth: 100 }}
                          />
                          <input
                            className="input"
                            placeholder="Value (e.g. formal)"
                            value={styleRuleValue}
                            onChange={(e) => setStyleRuleValue(e.target.value)}
                            style={{ flex: 1, minWidth: 100 }}
                          />
                          <button
                            className="btn btn-primary"
                            disabled={!styleRuleKey || !styleRuleValue}
                            onClick={() => {
                              void setStyleRule(styleRuleKey, styleRuleValue).then((res) => {
                                pushToast({
                                  title: res.ok ? 'Style rule set' : 'Failed to set style rule',
                                  description: `${styleRuleKey} = ${styleRuleValue}`,
                                  level: res.ok ? 'success' : 'error',
                                });
                                setStyleRuleKey('');
                                setStyleRuleValue('');
                                void loadAll();
                              });
                            }}
                          >
                            Apply
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </section>
              </div>

              <div className="operator-brief-grid" style={{ marginTop: 16 }}>
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Compensating Rollback</h3>
                    <span>{compensatingHistory.length} history / {compensators.length} compensators</span>
                  </div>
                  {wave2Loading ? (
                    <div className="empty-state" style={{ padding: 20 }}>
                      <span className="spinner" style={{ width: 18, height: 18 }} />
                      <p>Loading compensating data...</p>
                    </div>
                  ) : (
                    <div className="task-child-list">
                      {compensators.length > 0 && (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Available Compensators</span>
                            <span className="badge badge-blue">{compensators.length}</span>
                          </div>
                          <div className="task-child-preview">
                            {compensators.map((c: any) => c?.name || c?.integration || JSON.stringify(c)).join(', ')}
                          </div>
                        </div>
                      )}
                      {compensatingHistory.map((entry: any, idx: number) => (
                        <div key={entry?.id || entry?.compensation_id || idx} className="task-child-card">
                          <div className="task-child-top">
                            <span>{entry?.integration || entry?.action || `Entry ${idx + 1}`}</span>
                            <span className={`badge ${entry?.status === 'completed' ? 'badge-green' : entry?.status === 'failed' ? 'badge-orange' : 'badge-blue'}`}>
                              {entry?.status || 'recorded'}
                            </span>
                          </div>
                          <div className="task-child-preview">{entry?.action || entry?.description || JSON.stringify(entry)}</div>
                          {entry?.compensation_id && (
                            <div className="task-detail-actions" style={{ marginTop: 8 }}>
                              <button
                                className="btn btn-secondary"
                                onClick={() => {
                                  void executeCompensation(entry.compensation_id).then((res) => {
                                    pushToast({
                                      title: res.ok ? 'Compensation executed' : 'Compensation failed',
                                      description: String(entry.compensation_id),
                                      level: res.ok ? 'success' : 'error',
                                    });
                                    void loadAll();
                                  });
                                }}
                              >
                                Execute Rollback
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                      {compensatingHistory.length === 0 && compensators.length === 0 && (
                        <div className="empty-state" style={{ padding: 20 }}>
                          <span className="empty-icon">CMP</span>
                          <h3>No compensating data</h3>
                          <p>Compensating rollback history will appear once integrations produce reversible actions.</p>
                        </div>
                      )}
                    </div>
                  )}
                </section>

                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Skill Federation</h3>
                    <span>{federatedSkills.length} skills</span>
                  </div>
                  {wave2Loading ? (
                    <div className="empty-state" style={{ padding: 20 }}>
                      <span className="spinner" style={{ width: 18, height: 18 }} />
                      <p>Loading federation data...</p>
                    </div>
                  ) : (
                    <div className="task-child-list">
                      {federationStats && (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Federation Stats</span>
                            <span className="badge badge-blue">overview</span>
                          </div>
                          <div className="task-child-preview">
                            {Object.entries(federationStats).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ')}
                          </div>
                        </div>
                      )}
                      {federatedSkills.map((skill: any, idx: number) => (
                        <div key={skill?.name || skill?.skill_name || idx} className="task-child-card">
                          <div className="task-child-top">
                            <span>{skill?.name || skill?.skill_name || `Skill ${idx + 1}`}</span>
                            <span className={`badge ${skill?.status === 'active' ? 'badge-green' : 'badge-blue'}`}>
                              {skill?.source || skill?.peer_id || 'federated'}
                            </span>
                          </div>
                          <div className="task-child-preview">{skill?.description || JSON.stringify(skill)}</div>
                        </div>
                      ))}
                      {federatedSkills.length === 0 && !federationStats && (
                        <div className="empty-state" style={{ padding: 20 }}>
                          <span className="empty-icon">FED</span>
                          <h3>No federated skills</h3>
                          <p>Publish or import skills from federation peers to see them here.</p>
                        </div>
                      )}
                    </div>
                  )}
                </section>
              </div>

              <div className="operator-brief-grid" style={{ marginTop: 16 }}>
                <section className="operator-section-card">
                  <div className="operator-section-head">
                    <h3>Scheduler</h3>
                    <span>{schedulerStatus || 'unknown'}</span>
                  </div>
                  {wave2Loading ? (
                    <div className="empty-state" style={{ padding: 20 }}>
                      <span className="spinner" style={{ width: 18, height: 18 }} />
                      <p>Loading scheduler status...</p>
                    </div>
                  ) : (
                    <div className="task-child-list">
                      <div className="task-child-card">
                        <div className="task-child-top">
                          <span>Scheduler Status</span>
                          <span className={`badge ${schedulerStatus === 'running' ? 'badge-green' : schedulerStatus === 'paused' ? 'badge-orange' : 'badge-blue'}`}>
                            {schedulerStatus || 'unknown'}
                          </span>
                        </div>
                        <div className="task-child-preview">
                          The adaptive scheduler manages proactive routine execution.
                        </div>
                      </div>
                      {brief?.proactive_routines && brief.proactive_routines.length > 0 && (
                        <>
                          {brief.proactive_routines.map((routine: any) => (
                            <div key={String(routine.routine_id)} className="task-child-card">
                              <div className="task-child-top">
                                <span>{String(routine.title || routine.name || routine.routine_id)}</span>
                                <span className="badge">{String(routine.state || routine.probation_status || 'tracked')}</span>
                              </div>
                              <div className="task-detail-actions" style={{ marginTop: 8 }}>
                                <button
                                  className="btn btn-secondary"
                                  onClick={() => {
                                    void forceRunRoutine(String(routine.routine_id)).then((res) => {
                                      pushToast({
                                        title: res.ok ? 'Routine triggered' : 'Force-run failed',
                                        description: String(routine.routine_id),
                                        level: res.ok ? 'success' : 'error',
                                      });
                                      void loadAll();
                                    });
                                  }}
                                >
                                  Force Run
                                </button>
                              </div>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </section>
              </div>

            </div>
          )}

          {audit && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
                <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Recent Actions</h3>
                <div className="task-detail-chips">
                  <span className="badge">{audit.stats.total_records} audited</span>
                  <span className={`badge ${audit.stats.denied_records > 0 ? 'badge-orange' : 'badge-green'}`}>
                    {audit.stats.denied_records} denied
                  </span>
                </div>
              </div>
              <div className="info-box" style={{ marginBottom: 12 }}>
                <span className="info-icon">i</span>
                <span>
                  This is the runtime action trail for tool use and policy decisions. Use it to verify what the agent actually executed, which tools were blocked, and whether results came from real actions instead of model guesswork.
                </span>
              </div>
              {audit.events.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {audit.events.map((event, index) => (
                    <div key={`${event.request_id || event.tool_name}-${index}`} className="card" style={{ padding: 12 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', marginBottom: 8, flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span className={`badge ${event.allowed ? (event.success ? 'badge-green' : 'badge-orange') : 'badge-red'}`}>
                            {event.allowed ? (event.success ? 'allowed' : 'failed') : 'denied'}
                          </span>
                          <span className="badge badge-blue">{event.tool_name || 'unknown tool'}</span>
                          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{event.action}</span>
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                          <span>{new Date(event.timestamp * 1000).toLocaleTimeString()}</span>
                          <span>{Math.round(event.execution_time_ms)} ms</span>
                          {event.platform ? <span>{event.platform}</span> : null}
                        </div>
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 6 }}>
                        {event.denied_reason || event.result_preview || 'No result preview recorded.'}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', wordBreak: 'break-word' }}>
                        Args: {event.args_preview || 'No args preview captured.'}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">ACT</span>
                  <h3>No audited actions yet</h3>
                  <p>Once the agent uses tools, the action trail will appear here.</p>
                </div>
              )}
            </div>
          )}

          {/* Health Banner */}
          {health && (
            <div className="info-box" style={{
              marginBottom: 16,
              background: health.status === 'healthy' ? 'var(--accent-green-muted)' : 'var(--accent-red-muted)',
              borderColor: health.status === 'healthy' ? 'rgba(63,185,80,0.3)' : 'rgba(248,81,73,0.3)',
            }}>
              <span className="info-icon">{health.status === 'healthy' ? '✅' : '⚠️'}</span>
              <span>
                Backend {health.status === 'healthy' ? 'online' : health.status}
                {health.version && ` — v${health.version}`}
                {health.uptime && ` — uptime ${health.uptime}`}
                {runtimePhase && ` — phase ${runtimePhaseLabel}`}
              </span>
            </div>
          )}

          {/* Stats Grid */}
          <div className="stats-grid" style={{ marginBottom: 24 }}>
            <div className="stat-card">
              <div className="stat-label">Runtime Route</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{runtimeRouteLabel}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Configured Primary</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{configuredPrimaryLabel}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Runtime Phase</div>
              <div className="stat-value" style={{ fontSize: 16 }}>{runtimePhaseLabel}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Active Model</div>
              <div className="stat-value" style={{ fontSize: 15 }}>{stats?.active_model ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Interactions</div>
              <div className="stat-value">{stats?.interactions ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Success Rate</div>
              <div className="stat-value">
                {stats?.success_rate != null ? `${(stats.success_rate * 100).toFixed(0)}%` : '—'}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Observability</div>
              <div className="stat-value" style={{ fontSize: 15 }}>
                {observabilityHealthy ? 'Traces live' : 'Partial'}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Bus Events</div>
              <div className="stat-value">{stats?.event_count ?? events.length}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Uptime</div>
              <div className="stat-value" style={{ fontSize: 16 }}>{stats?.uptime || health?.uptime || '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Skills Loaded</div>
              <div className="stat-value">{stats?.skills ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Channels</div>
              <div className="stat-value" style={{ fontSize: 14 }}>{stats?.channels ?? '—'}</div>
            </div>
          </div>

          {/* Provider Status */}
          {providers.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
                <div>
                  <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>Runtime Route</h3>
                  <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0, maxWidth: 720 }}>
                    This card reflects the route the backend reports as active. The inventory below is configuration and availability only; it does not prove current execution.
                  </p>
                </div>
                {(runtimeRouteLabel || configuredPrimaryLabel) && (
                  <div
                    className="card"
                    style={{
                      padding: '12px 14px',
                      minWidth: 280,
                      border: '1px solid rgba(59,130,246,0.35)',
                      background: 'linear-gradient(135deg, rgba(37,99,235,0.16), rgba(15,23,42,0.92))',
                    }}
                  >
                    <div style={{ fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 8 }}>
                      Active Runtime Contract
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{
                        width: 34, height: 34, borderRadius: '50%',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: (PROVIDER_COLORS[runtimeRouteLabel as ProviderId] || { bg: '#6b7280', text: '#fff' }).bg,
                        color: (PROVIDER_COLORS[runtimeRouteLabel as ProviderId] || { bg: '#6b7280', text: '#fff' }).text,
                        fontSize: 14, fontWeight: 700,
                      }}>
                        {(PROVIDER_COLORS[runtimeRouteLabel as ProviderId] || { icon: '?' }).icon}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 15, fontWeight: 700 }}>
                          {(PROVIDER_COLORS[runtimeRouteLabel as ProviderId] || { label: runtimeRouteLabel }).label}
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                          <span style={{
                            width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
                            background: health?.status === 'healthy' ? '#3fb950' : '#f85149',
                          }} />
                          <span>{health?.status === 'healthy' ? 'Runtime route ready' : 'Runtime route degraded'}</span>
                          <span>• Configured primary {configuredPrimaryLabel}</span>
                          <span>• Phase {runtimePhaseLabel}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Provider Inventory</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
                {providers.map((p) => {
                  const pid = p.name as ProviderId;
                  const colors = PROVIDER_COLORS[pid] || { bg: '#6b7280', text: '#fff', icon: '?', label: p.name };
                  const optionalOffline = !p.is_primary && !p.available;
                  return (
                    <div
                      key={p.name}
                      className="card"
                      style={{
                        padding: '12px 14px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        border: p.is_primary ? '2px solid var(--accent-blue)' : undefined,
                        opacity: optionalOffline ? 0.78 : 1,
                      }}
                    >
                      <div style={{
                        width: 32, height: 32, borderRadius: '50%',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: colors.bg, color: colors.text,
                        fontSize: 14, fontWeight: 700,
                      }}>
                        {colors.icon}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                          {colors.label || p.name}
                          {p.is_primary && (
                            <span className="badge badge-blue" style={{ fontSize: 9, padding: '1px 5px' }}>
                              PRIMARY
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{
                            width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
                            background: p.available ? '#3fb950' : '#f85149',
                          }} />
                          {p.available ? (p.is_primary ? 'Primary route online' : 'Available') : (p.is_primary ? 'Primary route offline' : 'Optional route offline')}
                          {!p.has_key && p.name !== 'local' && p.name !== 'meta' && (
                            <span style={{ color: '#e5a100' }}>• No key</span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Recent Traces */}
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Recent Traces</h3>
            {traces.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {traces.slice(-10).reverse().map((t, i) => (
                  <div key={i} className="card" style={{ padding: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                      <span className={`badge ${t.category === 'memory' ? 'badge-blue' : t.category === 'reasoning' ? 'badge-purple' : t.category === 'action' ? 'badge-green' : 'badge-orange'}`}>
                        {t.category}
                      </span>
                      {t.reasoning_path ? <span className="badge">{t.reasoning_path}</span> : null}
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {new Date(t.timestamp * 1000).toLocaleTimeString()}
                      </span>
                      {t.trace_id ? <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.trace_id}</span> : null}
                    </div>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>{renderTraceSummary(t)}</p>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
                      {t.total_tool_calls != null ? <span>tools {t.total_tool_calls}</span> : null}
                      {t.duration_ms != null ? <span>{Math.round(t.duration_ms)} ms</span> : null}
                      {t.confidence != null ? <span>confidence {(t.confidence * 100).toFixed(0)}%</span> : null}
                      {t.error ? <span style={{ color: '#f85149' }}>error {t.error}</span> : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state" style={{ padding: 24 }}>
                <span className="empty-icon">📊</span>
                <h3>No Traces Yet</h3>
                <p>Send a message in Chat — traces will appear here as NeuralClaw processes requests.</p>
              </div>
            )}
          </div>

          {/* Event Bus */}
          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Event Bus</h3>
            {events.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {events.slice(-8).reverse().map((ev, i) => (
                  <div key={i} style={{
                    padding: '6px 12px', background: 'var(--bg-card)', borderRadius: 'var(--radius-sm)',
                    display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, fontFamily: 'var(--font-mono)',
                    border: '1px solid var(--border)',
                    flexWrap: 'wrap',
                  }}>
                    <span style={{ color: 'var(--text-muted)', width: 70 }}>
                      {ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : ''}
                    </span>
                    <span style={{
                      color: ev.level === 'error'
                        ? '#f85149'
                        : ev.level === 'success'
                          ? '#3fb950'
                          : ev.level === 'warning'
                            ? '#e3b341'
                            : 'var(--accent-blue)',
                      fontWeight: 600,
                    }}>
                      {ev.type}
                    </span>
                    <span style={{ color: 'var(--text-muted)', flex: 1 }}>{ev.source}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{ev.data_preview}</span>
                    {ev.correlation_id ? (
                      <span style={{ color: 'var(--text-muted)' }}>
                        corr {ev.correlation_id}
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No events yet — they appear as NeuralClaw processes requests.</p>
            )}
          </div>

          <button className="btn btn-secondary" onClick={loadAll} disabled={refreshing}>
            {refreshing ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Refreshing...</> : '🔄 Refresh All'}
          </button>
        </div>
      </div>
    </>
  );
}
