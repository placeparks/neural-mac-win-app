import { useEffect, useMemo, useState } from 'react';
import Header from '../components/layout/Header';
import {
  createAdaptiveSnapshot,
  createDesktopChatSessionWithMetadata,
  executeAdaptiveRollback,
  saveDesktopChatDraft,
  saveDesktopChatMessage,
} from '../lib/api';
import { useAppStore } from '../store/appStore';
import { useTaskStore } from '../store/taskStore';

function formatTaskTime(value?: number | null) {
  if (!value) return 'Pending';
  const timestamp = value > 1_000_000_000_000 ? value : value * 1000;
  return new Date(timestamp).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(durationMs?: number | null) {
  if (!durationMs) return 'Active';
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`;
  return `${(durationMs / 1000).toFixed(1)} s`;
}

function taskStatusTone(status?: string | null) {
  if (status === 'completed' || status === 'approved') return 'green';
  if (status === 'failed' || status === 'rejected') return 'red';
  if (status === 'partial' || status === 'awaiting_approval' || status === 'pending') return 'orange';
  return 'blue';
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
}

type TaskSectionKey =
  | 'approval'
  | 'brief'
  | 'prompt'
  | 'result'
  | 'trust'
  | 'review'
  | 'memory'
  | 'artifacts'
  | 'timeline'
  | 'children';

export default function TasksPage() {
  const {
    tasks,
    selectedTaskId,
    taskDetails,
    loading,
    loadTasks,
    loadTask,
    selectTask,
    approveTaskById,
    rejectTaskById,
  } = useTaskStore();
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'pending' | 'completed' | 'failed'>('all');
  const [actionableOnly, setActionableOnly] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Record<TaskSectionKey, boolean>>({
    approval: false,
    brief: false,
    prompt: true,
    result: false,
    trust: false,
    review: true,
    memory: true,
    artifacts: false,
    timeline: false,
    children: true,
  });
  const pushToast = useAppStore((state) => state.pushToast);
  const pendingTasks = tasks.filter((task) => task.status === 'pending' || task.status === 'awaiting_approval').length;
  const completedTasks = tasks.filter((task) => task.status === 'completed' || task.status === 'approved').length;
  const activeTasks = tasks.filter((task) => !['completed', 'approved', 'failed', 'rejected'].includes(task.status)).length;

  useEffect(() => {
    void loadTasks(80);
  }, [loadTasks]);

  useEffect(() => {
    if (!selectedTaskId && tasks[0]?.task_id) {
      selectTask(tasks[0].task_id);
      void loadTask(tasks[0].task_id);
    }
  }, [loadTask, selectTask, selectedTaskId, tasks]);

  const filteredTasks = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const matchesStatus = (status: string) => {
      if (statusFilter === 'all') return true;
      if (statusFilter === 'active') return !['completed', 'approved', 'failed', 'rejected'].includes(status);
      if (statusFilter === 'pending') return ['pending', 'awaiting_approval'].includes(status);
      if (statusFilter === 'completed') return ['completed', 'approved'].includes(status);
      if (statusFilter === 'failed') return ['failed', 'rejected'].includes(status);
      return true;
    };

    return tasks
      .filter((task) => matchesStatus(task.status))
      .filter((task) => (
        !actionableOnly
        || task.status === 'awaiting_approval'
        || !['completed', 'approved', 'failed', 'rejected'].includes(task.status)
      ))
      .filter((task) => {
        if (!normalizedQuery) return true;
        const haystack = [
          task.title,
          task.prompt,
          task.result_preview,
          task.provider,
          task.effective_model,
          task.requested_model,
          ...task.target_agents,
        ]
          .join(' ')
          .toLowerCase();
        return haystack.includes(normalizedQuery);
      })
      .sort((a, b) => {
        const statusRank = (status: string) => {
          if (status === 'awaiting_approval') return 0;
          if (status === 'pending') return 1;
          if (status === 'running') return 2;
          if (status === 'completed' || status === 'approved') return 3;
          if (status === 'failed' || status === 'rejected') return 4;
          return 5;
        };
        const rankDelta = statusRank(a.status) - statusRank(b.status);
        if (rankDelta !== 0) return rankDelta;
        return (b.updated_at || 0) - (a.updated_at || 0);
      });
  }, [actionableOnly, searchQuery, statusFilter, tasks]);

  useEffect(() => {
    if (!filteredTasks.length) return;
    if (!selectedTaskId || !filteredTasks.some((task) => task.task_id === selectedTaskId)) {
      selectTask(filteredTasks[0].task_id);
      void loadTask(filteredTasks[0].task_id);
    }
  }, [filteredTasks, loadTask, selectTask, selectedTaskId]);

  const selectedTask = useMemo(() => {
    if (!selectedTaskId) return null;
    return taskDetails[selectedTaskId] || tasks.find((task) => task.task_id === selectedTaskId) || null;
  }, [selectedTaskId, taskDetails, tasks]);
  const selectedTaskIndex = selectedTask ? filteredTasks.findIndex((task) => task.task_id === selectedTask.task_id) : -1;
  const previousTask = selectedTaskIndex > 0 ? filteredTasks[selectedTaskIndex - 1] : null;
  const nextTask = selectedTaskIndex >= 0 && selectedTaskIndex < filteredTasks.length - 1 ? filteredTasks[selectedTaskIndex + 1] : null;
  const selectedProvenance = Array.isArray(selectedTask?.metadata?.memory_provenance)
    ? selectedTask?.metadata?.memory_provenance as Array<Record<string, unknown>>
    : [];
  const selectedScopes = Array.isArray(selectedTask?.metadata?.memory_scopes)
    ? selectedTask?.metadata?.memory_scopes as string[]
    : [];
  const selectedBrief = asRecord(selectedTask?.metadata?.brief);
  const selectedLog = Array.isArray(selectedTask?.metadata?.execution_log)
    ? selectedTask?.metadata?.execution_log as Array<Record<string, unknown>>
    : [];
  const selectedArtifacts = Array.isArray(selectedTask?.metadata?.artifacts)
    ? selectedTask?.metadata?.artifacts as Array<Record<string, unknown>>
    : [];
  const selectedFollowups = Array.isArray(selectedTask?.metadata?.followups)
    ? selectedTask?.metadata?.followups as string[]
    : [];
  const selectedPlan = asRecord(selectedTask?.metadata?.plan);
  const selectedReview = asRecord(selectedTask?.metadata?.review);
  const selectedCheckpoints = Array.isArray(selectedTask?.metadata?.checkpoints)
    ? selectedTask?.metadata?.checkpoints as Array<Record<string, unknown>>
    : [];
  const selectedSteps = Array.isArray(selectedTask?.metadata?.steps)
    ? selectedTask?.metadata?.steps as Array<Record<string, unknown>>
    : [];
  const briefDeliverables = Array.isArray(selectedBrief.deliverables)
    ? selectedBrief.deliverables.map((item) => String(item))
    : [];
  const briefIntegrations = Array.isArray(selectedBrief.integration_targets)
    ? selectedBrief.integration_targets.map((item) => String(item))
    : [];
  const approvalState = asRecord(selectedTask?.metadata?.approval);
  const approvalStatus = String(approvalState.status || (selectedTask?.status === 'awaiting_approval' ? 'pending' : 'not_required'));
  const approvalRequired = Boolean(approvalState.required || selectedTask?.status === 'awaiting_approval');
  const approvalNote = String(approvalState.note || '');
  const approvalRejectedReason = String(approvalState.rejected_reason || '');
  const confidenceContract = asRecord(selectedTask?.metadata?.confidence_contract);
  const changeReceipt = asRecord(selectedTask?.metadata?.change_receipt);
  const changeReceiptFiles = Array.isArray(changeReceipt.files_changed)
    ? changeReceipt.files_changed.map((item) => String(item)).filter(Boolean)
    : [];
  const changeReceiptHasRollback = Boolean(changeReceipt.rollback_available || changeReceipt.snapshot_id);
  const changeReceiptRolledBack = Boolean(changeReceipt.rollback_token);
  const changeReceiptCoverage = asRecord(changeReceipt.rollback_coverage);
  const changeReceiptResources = Array.isArray(changeReceipt.resource_entries)
    ? changeReceipt.resource_entries as Array<Record<string, unknown>>
    : [];

  const handleApprove = async () => {
    if (!selectedTask) return;
    const note = window.prompt('Optional approval note', approvalNote) || '';
    setApprovalBusy(true);
    const ok = await approveTaskById(selectedTask.task_id, note);
    if (ok) {
      await loadTask(selectedTask.task_id);
    }
    setApprovalBusy(false);
  };

  const handleReject = async () => {
    if (!selectedTask) return;
    const reason = window.prompt('Reason for rejection', approvalRejectedReason || approvalNote) || '';
    setApprovalBusy(true);
    const ok = await rejectTaskById(selectedTask.task_id, reason);
    if (ok) {
      await loadTask(selectedTask.task_id);
    }
    setApprovalBusy(false);
  };

  const openTaskChat = async (mode: 'open' | 'followup') => {
    if (!selectedTask) return;
    const primaryAgent = selectedTask.target_agents[0] || 'agent';
    const title = selectedTask.target_agents.length === 1
      ? `Agent: ${primaryAgent}`
      : `Task: ${selectedTask.title}`;
    const bootstrap = await createDesktopChatSessionWithMetadata(title, {
      targetAgent: selectedTask.target_agents.length === 1 ? primaryAgent : null,
      selectedProvider: selectedTask.provider || null,
      selectedModel: selectedTask.effective_model || selectedTask.requested_model || null,
      baseUrl: selectedTask.base_url || null,
      projectContextId: String(selectedTask.metadata?.project_context_id || '') || null,
      teachingMode: Array.isArray(selectedTask.metadata?.teaching_artifacts) && selectedTask.metadata.teaching_artifacts.length > 0,
      autonomyMode: (String(selectedTask.metadata?.autonomy_mode || 'suggest-first') as 'observe-only' | 'suggest-first' | 'auto-run-low-risk' | 'policy-driven-autonomous'),
    });
    const sessionId = bootstrap.activeSessionId;
    await saveDesktopChatMessage(sessionId, {
      role: 'user',
      content: selectedTask.prompt,
      timestamp: new Date().toISOString(),
    });
    if (selectedTask.result) {
      await saveDesktopChatMessage(sessionId, {
        role: 'assistant',
        content: selectedTask.result,
        timestamp: new Date().toISOString(),
      });
    }
    if (mode === 'followup') {
      await saveDesktopChatDraft(
        sessionId,
        `Follow up on task "${selectedTask.title}" and continue from the last result.`,
      );
    }
    window.dispatchEvent(new CustomEvent('neuralclaw:navigate', { detail: 'chat' }));
  };

  const captureTaskSnapshot = async () => {
    if (!selectedTask || changeReceiptFiles.length === 0) return;
    const result = await createAdaptiveSnapshot({
      task_id: selectedTask.task_id,
      file_paths: changeReceiptFiles,
      metadata: { source: 'tasks_page', receipt_id: String(changeReceipt.receipt_id || '') },
    });
    pushToast({
      title: result.ok ? 'Snapshot captured' : 'Snapshot failed',
      description: result.ok ? (result.snapshot_id || selectedTask.task_id) : (result.error || 'Unable to capture snapshot.'),
      level: result.ok ? 'success' : 'error',
    });
    if (result.ok) {
      await loadTask(selectedTask.task_id);
      await loadTasks(80);
    }
  };

  const rollbackTaskReceipt = async () => {
    if (!selectedTask || !changeReceipt.receipt_id) return;
    const result = await executeAdaptiveRollback({ receipt_id: String(changeReceipt.receipt_id) });
    pushToast({
      title: result.ok ? 'Rollback completed' : 'Rollback failed',
      description: result.ok
        ? `${result.restored_paths?.length || 0} restored, ${result.deleted_paths?.length || 0} removed`
        : (result.error || 'Unable to execute rollback.'),
      level: result.ok ? 'success' : 'error',
    });
    await loadTask(selectedTask.task_id);
    await loadTasks(80);
  };

  const jumpToSection = (sectionId: string) => {
    const element = document.getElementById(sectionId);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const toggleSection = (section: TaskSectionKey) => {
    setCollapsedSections((state) => ({ ...state, [section]: !state[section] }));
  };

  const detailSections = [
    { id: 'task-section-brief', label: 'Brief', visible: Boolean(selectedTask && (selectedBrief.success_criteria || selectedBrief.workspace_path || briefDeliverables.length > 0 || briefIntegrations.length > 0)) },
    { id: 'task-section-result', label: 'Result', visible: Boolean(selectedTask) },
    { id: 'task-section-trust', label: 'Trust', visible: Object.keys(confidenceContract).length > 0 || Object.keys(changeReceipt).length > 0 },
    { id: 'task-section-review', label: 'Review', visible: Object.keys(selectedPlan).length > 0 || Object.keys(selectedReview).length > 0 || selectedCheckpoints.length > 0 },
    { id: 'task-section-memory', label: 'Memory', visible: selectedScopes.length > 0 || selectedProvenance.length > 0 },
    { id: 'task-section-artifacts', label: 'Artifacts', visible: selectedArtifacts.length > 0 || selectedFollowups.length > 0 },
    { id: 'task-section-timeline', label: 'Timeline', visible: selectedLog.length > 0 || selectedSteps.length > 0 },
    { id: 'task-section-children', label: 'Children', visible: Boolean(selectedTask?.children?.length) },
  ].filter((item) => item.visible);

  return (
    <>
      <Header title="Tasks" />
      <div className="app-content">
        <div className="control-room">
          <section className="control-room-rail">
            <div className="tasks-command-deck">
              <div>
                <div className="eyebrow">Task Control Room</div>
                <h2>Persistent delegated work with review, rollback, and follow-through</h2>
                <p>
                  Use the inbox to inspect what agents actually did, approve sensitive work, and continue important runs from the exact execution record.
                </p>
              </div>
              <div className="tasks-command-stats">
                <div className="tasks-command-stat">
                  <span>Pending</span>
                  <strong>{pendingTasks}</strong>
                </div>
                <div className="tasks-command-stat">
                  <span>Active</span>
                  <strong>{activeTasks}</strong>
                </div>
                <div className="tasks-command-stat">
                  <span>Completed</span>
                  <strong>{completedTasks}</strong>
                </div>
              </div>
            </div>
            <div className="control-room-header">
              <div>
                <h1>Task Inbox</h1>
                <p>Search, filter, and step through durable execution records without losing context.</p>
              </div>
              <button className="btn btn-secondary" onClick={() => void loadTasks(80)}>
                Refresh
              </button>
            </div>
            <div className="info-box" style={{ margin: '0 16px 16px' }}>
              <span className="info-icon">i</span>
              <span>
                This is the durable execution inbox. Use it to approve gated work, inspect what agents actually did, and continue important runs from chat without losing history.
              </span>
            </div>
            <div className="task-inbox-toolbar">
              <input
                className="input"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search title, prompt, agent, provider, or model..."
              />
              <select
                className="select"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as 'all' | 'active' | 'pending' | 'completed' | 'failed')}
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="pending">Pending approval</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
              </select>
              <button
                type="button"
                className={`btn ${actionableOnly ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setActionableOnly((value) => !value)}
              >
                {actionableOnly ? 'Showing Actionable' : 'Actionable Only'}
              </button>
            </div>
            <div className="task-inbox-summary">
              <span>{filteredTasks.length} visible</span>
              <span>•</span>
              <span>{pendingTasks} pending review</span>
              <span>•</span>
              <span>{activeTasks} active</span>
              <span>•</span>
              <span>{completedTasks} completed</span>
            </div>
            <div className="task-list">
              {loading && tasks.length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="spinner" style={{ width: 20, height: 20 }} />
                  <p>Loading task inbox...</p>
                </div>
              ) : tasks.length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">TK</span>
                  <h3>No delegated tasks yet</h3>
                  <p>Tasks created from the Agents panel will appear here and survive restarts.</p>
                </div>
              ) : filteredTasks.length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">FL</span>
                  <h3>No tasks match this filter</h3>
                  <p>Broaden search terms or switch off actionable-only mode to see the full inbox again.</p>
                </div>
              ) : (
                filteredTasks.map((task) => (
                  <button
                    key={task.task_id}
                    type="button"
                    className={`task-card ${selectedTaskId === task.task_id ? 'active' : ''}`}
                    onClick={() => {
                      selectTask(task.task_id);
                      void loadTask(task.task_id);
                    }}
                  >
                    <div className="task-card-top">
                      <span className={`badge badge-${taskStatusTone(task.status)}`}>
                        {task.status}
                      </span>
                      <span className="task-card-time">{formatTaskTime(task.updated_at)}</span>
                    </div>
                    <div className="task-card-title">{task.title}</div>
                    <div className="task-card-meta">
                      <span>{task.target_agents.join(', ') || 'dashboard'}</span>
                      <span>{task.effective_model || task.requested_model || 'auto'}</span>
                    </div>
                    <div className="task-card-preview">{task.result_preview || task.prompt}</div>
                  </button>
                ))
              )}
            </div>
          </section>

          <section className="control-room-detail">
            {!selectedTask ? (
              <div className="empty-state" style={{ padding: 32 }}>
                <span className="empty-icon">OP</span>
                <h3>Select a task</h3>
                <p>Inspect delegation results, fallback behavior, and open the linked agent chat.</p>
              </div>
            ) : (
              <div className="task-detail-panel">
                <div className="task-detail-header">
                  <div>
                    <div className="task-detail-eyebrow">Delegation Record</div>
                    <h2>{selectedTask.title}</h2>
                    <div className="task-detail-chips">
                      <span className={`badge badge-${taskStatusTone(selectedTask.status)}`}>
                        {selectedTask.status}
                      </span>
                      <span className="badge">{selectedTask.provider || 'primary'}</span>
                      <span className="badge">{selectedTask.effective_model || selectedTask.requested_model || 'auto'}</span>
                    </div>
                  </div>
                  <div className="task-detail-actions">
                    <button
                      className="btn btn-secondary"
                      disabled={!previousTask}
                      onClick={() => {
                        if (!previousTask) return;
                        selectTask(previousTask.task_id);
                        void loadTask(previousTask.task_id);
                      }}
                    >
                      Prev
                    </button>
                    <button
                      className="btn btn-secondary"
                      disabled={!nextTask}
                      onClick={() => {
                        if (!nextTask) return;
                        selectTask(nextTask.task_id);
                        void loadTask(nextTask.task_id);
                      }}
                    >
                      Next
                    </button>
                    <button className="btn btn-secondary" onClick={() => { void openTaskChat('open'); }}>
                      Open In Chat
                    </button>
                    <button className="btn btn-primary" onClick={() => { void openTaskChat('followup'); }}>
                      Send Follow-up
                    </button>
                  </div>
                </div>

                <div className="info-box">
                  <span className="info-icon">i</span>
                  <span>
                    Read this record top to bottom: execution mode, approval state, brief, result, then timeline. If something looks wrong, open the linked chat and continue from the exact task context instead of starting over.
                  </span>
                </div>

                <div className="task-detail-nav">
                  {detailSections.map((section) => (
                    <button
                      key={section.id}
                      type="button"
                      className="task-detail-nav-chip"
                      onClick={() => jumpToSection(section.id)}
                    >
                      {section.label}
                    </button>
                  ))}
                </div>

                <div className="task-record-summary">
                  <span>Updated {formatTaskTime(selectedTask.updated_at)}</span>
                  <span>Created {formatTaskTime(selectedTask.created_at)}</span>
                  {selectedTask.shared_task_id ? <span>Shared {selectedTask.shared_task_id}</span> : null}
                  {selectedTask.parent_task_id ? <span>Parent {selectedTask.parent_task_id}</span> : null}
                  <button
                    type="button"
                    className="task-collapse-toggle"
                    onClick={() => setCollapsedSections({
                      approval: true,
                      brief: true,
                      prompt: true,
                      result: false,
                      trust: false,
                      review: true,
                      memory: true,
                      artifacts: false,
                      timeline: false,
                      children: true,
                    })}
                  >
                    Focus result
                  </button>
                  <button
                    type="button"
                    className="task-collapse-toggle"
                    onClick={() => setCollapsedSections({
                      approval: false,
                      brief: false,
                      prompt: false,
                      result: false,
                      trust: false,
                      review: false,
                      memory: false,
                      artifacts: false,
                      timeline: false,
                      children: false,
                    })}
                  >
                    Expand all
                  </button>
                </div>

                <div className="task-metrics-grid">
                  <div className="metric-card">
                    <div className="metric-label">Agents</div>
                    <div className="metric-value">{selectedTask.target_agents.join(', ') || 'dashboard'}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Requested Model</div>
                    <div className="metric-value">{selectedTask.requested_model || 'auto'}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Effective Model</div>
                    <div className="metric-value">{selectedTask.effective_model || selectedTask.requested_model || 'auto'}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Runtime</div>
                    <div className="metric-value">{formatDuration(selectedTask.duration_ms)}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Execution Mode</div>
                    <div className="metric-value">{String(selectedBrief.execution_mode || 'agent-task')}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Orchestration</div>
                    <div className="metric-value">{String(selectedBrief.orchestration_mode || 'manual')}</div>
                  </div>
                </div>

                {approvalRequired && (
                  <div id="task-section-brief" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Approval Gate</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('approval')}>
                        {collapsedSections.approval ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.approval && (
                      <>
                        <div className="task-child-list">
                          <div className="task-child-card">
                            <div className="task-child-top">
                              <span>Approval Status</span>
                              <span className={`badge badge-${taskStatusTone(approvalStatus)}`}>
                                {approvalStatus}
                              </span>
                            </div>
                            <div className="task-child-preview">
                              {approvalRejectedReason || approvalNote || 'This task requires explicit approval before execution.'}
                            </div>
                          </div>
                        </div>
                        {selectedTask.status === 'awaiting_approval' && (
                          <div className="task-detail-actions" style={{ marginTop: 12 }}>
                            <button className="btn btn-primary" disabled={approvalBusy} onClick={() => { void handleApprove(); }}>
                              {approvalBusy ? 'Updating...' : 'Approve And Run'}
                            </button>
                            <button className="btn btn-secondary" disabled={approvalBusy} onClick={() => { void handleReject(); }}>
                              Reject
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}

                {(selectedBrief.success_criteria || selectedBrief.workspace_path || briefDeliverables.length > 0 || briefIntegrations.length > 0) && (
                  <div className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Execution Brief</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('brief')}>
                        {collapsedSections.brief ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.brief && (
                      <div className="task-child-list">
                        {selectedBrief.success_criteria ? (
                          <div className="task-child-card">
                            <div className="task-child-top"><span>Success Criteria</span></div>
                            <div className="task-child-preview">{String(selectedBrief.success_criteria)}</div>
                          </div>
                        ) : null}
                        {selectedBrief.workspace_path ? (
                          <div className="task-child-card">
                            <div className="task-child-top"><span>Workspace</span></div>
                            <div className="task-child-preview">{String(selectedBrief.workspace_path)}</div>
                          </div>
                        ) : null}
                        {briefDeliverables.length > 0 ? (
                          <div className="task-child-card">
                            <div className="task-child-top"><span>Deliverables</span></div>
                            <div className="task-child-preview">{briefDeliverables.join(', ')}</div>
                          </div>
                        ) : null}
                        {briefIntegrations.length > 0 ? (
                          <div className="task-child-card">
                            <div className="task-child-top"><span>Integrations</span></div>
                            <div className="task-child-preview">{briefIntegrations.join(', ')}</div>
                          </div>
                        ) : null}
                      </div>
                    )}
                  </div>
                )}

                <div className="task-detail-block">
                  <div className="task-detail-block-header">
                    <div className="task-detail-block-title">Prompt</div>
                    <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('prompt')}>
                      {collapsedSections.prompt ? 'Expand' : 'Collapse'}
                    </button>
                  </div>
                  {!collapsedSections.prompt && <pre className="task-detail-code">{selectedTask.prompt}</pre>}
                </div>

                <div id="task-section-result" className="task-detail-block">
                  <div className="task-detail-block-header">
                    <div className="task-detail-block-title">Result</div>
                    <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('result')}>
                      {collapsedSections.result ? 'Expand' : 'Collapse'}
                    </button>
                  </div>
                  {!collapsedSections.result && <pre className="task-detail-code">{selectedTask.result || selectedTask.error || 'Waiting for completion.'}</pre>}
                </div>

                {(Object.keys(confidenceContract).length > 0 || Object.keys(changeReceipt).length > 0) && (
                  <div id="task-section-trust" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Trust Signals</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('trust')}>
                        {collapsedSections.trust ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.trust && <div className="task-child-list">
                      {Object.keys(confidenceContract).length > 0 ? (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Confidence contract</span>
                            <span className="badge">{String(confidenceContract.confidence || 'n/a')}</span>
                          </div>
                          <div className="task-child-preview">
                            Source: {String(confidenceContract.source || 'unknown')} · Escalation: {String(confidenceContract.escalation_recommendation || 'none')}
                          </div>
                          {Array.isArray(confidenceContract.uncertainty_factors) && confidenceContract.uncertainty_factors.length > 0 ? (
                            <div className="task-child-meta">
                              <span>{(confidenceContract.uncertainty_factors as string[]).join(', ')}</span>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      {Object.keys(changeReceipt).length > 0 ? (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Change receipt</span>
                            <span className={`badge ${changeReceiptRolledBack ? 'badge-green' : changeReceiptHasRollback ? 'badge-orange' : 'badge-blue'}`}>
                              {changeReceiptRolledBack ? 'rolled-back' : changeReceiptHasRollback ? 'snapshot-ready' : 'captured'}
                            </span>
                          </div>
                          <div className="task-child-preview">
                            {Array.isArray(changeReceipt.operations) ? (changeReceipt.operations as string[]).join(', ') : 'No operations recorded.'}
                          </div>
                          {Object.keys(changeReceiptCoverage).length > 0 ? (
                            <div className="task-child-meta">
                              <span>{String(changeReceiptCoverage.summary || '')}</span>
                            </div>
                          ) : null}
                          {changeReceiptResources.length > 0 ? (
                            <div className="task-child-meta">
                              <span>
                                {changeReceiptResources.map((entry) => `${String(entry.resource_type || 'resource')}:${String(entry.rollback_kind || 'unknown')}`).join(' · ')}
                              </span>
                            </div>
                          ) : null}
                          <div className="task-detail-actions" style={{ marginTop: 12 }}>
                            <button
                              className="btn btn-secondary"
                              onClick={() => { void captureTaskSnapshot(); }}
                              disabled={changeReceiptFiles.length === 0}
                            >
                              Capture snapshot
                            </button>
                            <button
                              className="btn btn-secondary"
                              onClick={() => { void rollbackTaskReceipt(); }}
                              disabled={!changeReceiptHasRollback}
                            >
                              Roll back
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </div>}
                  </div>
                )}

                {(Object.keys(selectedPlan).length > 0 || Object.keys(selectedReview).length > 0 || selectedCheckpoints.length > 0) && (
                  <div id="task-section-review" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Stage Review</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('review')}>
                        {collapsedSections.review ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.review && <div className="task-child-list">
                      {Object.keys(selectedPlan).length > 0 && (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Plan</span>
                            <span className="badge">{String((selectedPlan.stages as Array<unknown> | undefined)?.length || 0)} stages</span>
                          </div>
                          <div className="task-child-preview">
                            {String(selectedPlan.task || selectedTask.prompt)}
                          </div>
                        </div>
                      )}
                      {Object.keys(selectedReview).length > 0 && (
                        <div className="task-child-card">
                          <div className="task-child-top">
                            <span>Reviewer Verdict</span>
                            <span className={`badge badge-${taskStatusTone(String(selectedReview.status || 'partial'))}`}>
                              {String(selectedReview.status || 'n/a')}
                            </span>
                          </div>
                          <div className="task-child-preview">
                            {String(selectedReview.summary || 'No review summary recorded.')}
                          </div>
                        </div>
                      )}
                      {selectedCheckpoints.map((checkpoint, index) => (
                        <div key={`checkpoint-${index}`} className="task-child-card">
                          <div className="task-child-top">
                            <span>{String(checkpoint.stage_role || `Stage ${index + 1}`)} · {String(checkpoint.agent || 'agent')}</span>
                            <span className={`badge badge-${taskStatusTone(String(checkpoint.status || 'partial'))}`}>
                              {String(checkpoint.status || 'unknown')}
                            </span>
                          </div>
                          <div className="task-child-preview">
                            {String(checkpoint.result || checkpoint.error || 'Checkpoint saved without output.')}
                          </div>
                        </div>
                      ))}
                    </div>}
                  </div>
                )}

                {(selectedScopes.length > 0 || selectedProvenance.length > 0) && (
                  <div id="task-section-memory" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Memory Context</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('memory')}>
                        {collapsedSections.memory ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.memory && (
                      <>
                        {selectedScopes.length > 0 ? (
                          <div className="task-detail-chips" style={{ marginBottom: 12 }}>
                            {selectedScopes.map((scope) => (
                              <span key={scope} className="badge">{scope}</span>
                            ))}
                          </div>
                        ) : null}
                        {selectedProvenance.length > 0 ? (
                          <div className="task-child-list">
                            {selectedProvenance.slice(0, 8).map((item, index) => (
                              <div key={`${String(item.item_id || index)}`} className="task-child-card">
                                <div className="task-child-top">
                                  <span>{String(item.title || item.memory_type || 'Memory')}</span>
                                  <span className="badge">{String(item.scope || 'global')}</span>
                                </div>
                                <div className="task-child-preview">
                                  {String(item.reason || item.excerpt || '')}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </>
                    )}
                  </div>
                )}

                {(selectedArtifacts.length > 0 || selectedFollowups.length > 0) && (
                  <div id="task-section-artifacts" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Artifacts & Next Steps</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('artifacts')}>
                        {collapsedSections.artifacts ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.artifacts && (
                      <>
                        {selectedArtifacts.length > 0 ? (
                          <div className="task-child-list" style={{ marginBottom: selectedFollowups.length > 0 ? 12 : 0 }}>
                            {selectedArtifacts.map((artifact, index) => (
                              <div key={`${String(artifact.value || index)}`} className="task-child-card">
                                <div className="task-child-top">
                                  <span>{String(artifact.label || artifact.type || 'Artifact')}</span>
                                  {artifact.agent ? <span className="badge">{String(artifact.agent)}</span> : null}
                                </div>
                                <div className="task-child-preview">{String(artifact.value || '')}</div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                        {selectedFollowups.length > 0 ? (
                          <div className="task-child-list">
                            {selectedFollowups.map((item, index) => (
                              <div key={`${index}-${item}`} className="task-child-card">
                                <div className="task-child-top"><span>Follow-up</span></div>
                                <div className="task-child-preview">{item}</div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </>
                    )}
                  </div>
                )}

                {(selectedLog.length > 0 || selectedSteps.length > 0) && (
                  <div id="task-section-timeline" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Execution Timeline</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('timeline')}>
                        {collapsedSections.timeline ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.timeline && <div className="task-child-list">
                      {selectedLog.map((entry, index) => (
                        <div key={`${String(entry.ts || index)}`} className="task-child-card">
                          <div className="task-child-top">
                            <span>{String(entry.event || 'event')}</span>
                            {entry.status ? <span className="badge">{String(entry.status)}</span> : null}
                          </div>
                          <div className="task-child-preview">
                            {String(entry.detail || '')}
                            {entry.agent ? ` (${String(entry.agent)})` : ''}
                          </div>
                        </div>
                      ))}
                      {selectedSteps.map((step, index) => (
                        <div key={`step-${index}`} className="task-child-card">
                          <div className="task-child-top">
                            <span>{String(step.agent || `Step ${index + 1}`)}</span>
                            <span className="badge">{String(step.status || 'done')}</span>
                          </div>
                          <div className="task-child-preview">{String(step.result || step.error || '')}</div>
                        </div>
                      ))}
                    </div>}
                  </div>
                )}

                {selectedTask.children?.length > 0 && (
                  <div id="task-section-children" className="task-detail-block">
                    <div className="task-detail-block-header">
                      <div className="task-detail-block-title">Child Tasks</div>
                      <button type="button" className="task-collapse-toggle" onClick={() => toggleSection('children')}>
                        {collapsedSections.children ? 'Expand' : 'Collapse'}
                      </button>
                    </div>
                    {!collapsedSections.children && <div className="task-child-list">
                      {selectedTask.children.map((child) => (
                        <div key={child.task_id} className="task-child-card">
                          <div className="task-child-top">
                            <span>{child.target_agents.join(', ') || 'agent'}</span>
                            <span className={`badge badge-${taskStatusTone(child.status)}`}>
                              {child.status}
                            </span>
                          </div>
                          <div className="task-child-meta">
                            <span>{child.requested_model || 'auto'}</span>
                            <span>{child.effective_model || child.requested_model || 'auto'}</span>
                          </div>
                          <div className="task-child-preview">{child.result_preview || child.error || child.prompt}</div>
                        </div>
                      ))}
                    </div>}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
