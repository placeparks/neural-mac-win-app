import { useEffect, useMemo } from 'react';
import Header from '../components/layout/Header';
import {
  createDesktopChatSessionWithMetadata,
  saveDesktopChatDraft,
  saveDesktopChatMessage,
} from '../lib/api';
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

export default function TasksPage() {
  const {
    tasks,
    selectedTaskId,
    taskDetails,
    loading,
    loadTasks,
    loadTask,
    selectTask,
  } = useTaskStore();

  useEffect(() => {
    void loadTasks(80);
  }, [loadTasks]);

  useEffect(() => {
    if (!selectedTaskId && tasks[0]?.task_id) {
      selectTask(tasks[0].task_id);
      void loadTask(tasks[0].task_id);
    }
  }, [loadTask, selectTask, selectedTaskId, tasks]);

  const selectedTask = useMemo(() => {
    if (!selectedTaskId) return null;
    return taskDetails[selectedTaskId] || tasks.find((task) => task.task_id === selectedTaskId) || null;
  }, [selectedTaskId, taskDetails, tasks]);

  const openTaskChat = async (mode: 'open' | 'followup') => {
    if (!selectedTask) return;
    const primaryAgent = selectedTask.target_agents[0] || 'agent';
    const title = selectedTask.target_agents.length === 1
      ? `Agent: ${primaryAgent}`
      : `Task: ${selectedTask.title}`;
    const bootstrap = await createDesktopChatSessionWithMetadata(title, {
      targetAgent: selectedTask.target_agents.length === 1 ? primaryAgent : null,
      selectedProvider: selectedTask.provider || 'local',
      selectedModel: selectedTask.effective_model || selectedTask.requested_model || null,
      baseUrl: selectedTask.base_url || null,
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

  return (
    <>
      <Header title="Tasks" />
      <div className="app-content">
        <div className="control-room">
          <section className="control-room-rail">
            <div className="control-room-header">
              <div>
                <h1>Task Inbox</h1>
                <p>Persistent delegated work with lifecycle tracking and model routing.</p>
              </div>
              <button className="btn btn-secondary" onClick={() => void loadTasks(80)}>
                Refresh
              </button>
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
              ) : (
                tasks.map((task) => (
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
                      <span className={`badge badge-${task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : task.status === 'partial' ? 'orange' : 'blue'}`}>
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
                      <span className={`badge badge-${selectedTask.status === 'completed' ? 'green' : selectedTask.status === 'failed' ? 'red' : selectedTask.status === 'partial' ? 'orange' : 'blue'}`}>
                        {selectedTask.status}
                      </span>
                      <span className="badge">{selectedTask.provider || 'local'}</span>
                      <span className="badge">{selectedTask.effective_model || selectedTask.requested_model || 'auto'}</span>
                    </div>
                  </div>
                  <div className="task-detail-actions">
                    <button className="btn btn-secondary" onClick={() => { void openTaskChat('open'); }}>
                      Open In Chat
                    </button>
                    <button className="btn btn-primary" onClick={() => { void openTaskChat('followup'); }}>
                      Send Follow-up
                    </button>
                  </div>
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
                </div>

                <div className="task-detail-block">
                  <div className="task-detail-block-title">Prompt</div>
                  <pre className="task-detail-code">{selectedTask.prompt}</pre>
                </div>

                <div className="task-detail-block">
                  <div className="task-detail-block-title">Result</div>
                  <pre className="task-detail-code">{selectedTask.result || selectedTask.error || 'Waiting for completion.'}</pre>
                </div>

                {selectedTask.children?.length > 0 && (
                  <div className="task-detail-block">
                    <div className="task-detail-block-title">Child Tasks</div>
                    <div className="task-child-list">
                      {selectedTask.children.map((child) => (
                        <div key={child.task_id} className="task-child-card">
                          <div className="task-child-top">
                            <span>{child.target_agents.join(', ') || 'agent'}</span>
                            <span className={`badge badge-${child.status === 'completed' ? 'green' : child.status === 'failed' ? 'red' : child.status === 'partial' ? 'orange' : 'blue'}`}>
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
                    </div>
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
