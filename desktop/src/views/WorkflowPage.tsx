// NeuralClaw Desktop — Workflow Page

import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';

interface WorkflowStep {
  id: string;
  name: string;
  action: string;
  status: string;
  depends_on: string[];
}

interface Workflow {
  id: string;
  name: string;
  status: string;
  steps: WorkflowStep[];
  created_at?: string;
  last_run?: string;
}

export default function WorkflowPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSteps, setNewSteps] = useState('');
  const [creating, setCreating] = useState(false);
  const [endpointAvailable, setEndpointAvailable] = useState(true);

  const loadWorkflows = useCallback(async () => {
    try {
      const result = await invoke<string>('get_workflows');
      const parsed = JSON.parse(result);
      setWorkflows(Array.isArray(parsed) ? parsed : parsed.workflows || []);
      setError(null);
      setEndpointAvailable(true);
    } catch {
      setWorkflows([]);
      setEndpointAvailable(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadWorkflows(); }, [loadWorkflows]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      let steps: object[] = [];
      if (newSteps.trim()) {
        steps = JSON.parse(newSteps);
      }
      await invoke<string>('create_workflow', {
        workflow: { name: newName, steps },
      });
      setNewName('');
      setNewSteps('');
      setShowCreate(false);
      await loadWorkflows();
    } catch (err) {
      setError('Create failed. Try using chat: "create workflow ' + newName + '"');
    } finally {
      setCreating(false);
    }
  };

  const handleRun = async (workflowId: string) => {
    setError(null);
    try {
      await invoke<string>('run_workflow', { workflowId });
      await loadWorkflows();
    } catch {
      setError('Run failed. Try using chat: "run workflow..."');
    }
  };

  const handlePause = async (workflowId: string) => {
    try {
      await invoke<string>('pause_workflow', { workflowId });
      await loadWorkflows();
    } catch { /* */ }
  };

  const handleDelete = async (workflowId: string) => {
    try {
      await invoke<string>('delete_workflow', { workflowId });
      await loadWorkflows();
    } catch { /* */ }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'running': return 'var(--accent-green)';
      case 'paused': return 'var(--accent-yellow, #e3b341)';
      case 'completed': return 'var(--accent-blue)';
      case 'failed': return 'var(--accent-red)';
      default: return 'var(--text-muted)';
    }
  };

  return (
    <>
      <Header title="Workflows" />
      <div className="app-content">
        <div className="page-header">
          <h1>⚡ Workflow Manager</h1>
          <p>Create and run multi-step task automations with DAG-based execution.</p>
        </div>

        <div className="page-body">
          {error && (
            <div className="info-box" style={{ background: 'var(--accent-red-muted)', borderColor: 'rgba(248,81,73,0.3)', marginBottom: 16 }}>
              <span className="info-icon">!</span>
              <span>{error}</span>
            </div>
          )}

          {!endpointAvailable && (
            <div className="info-box" style={{ marginBottom: 16 }}>
              <span className="info-icon">💡</span>
              <span>Workflow operations work through chat. See commands below.</span>
            </div>
          )}

          {/* Create Workflow */}
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Create Workflow</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowCreate(!showCreate)}>
                {showCreate ? 'Cancel' : '+ New'}
              </button>
            </div>
            {showCreate && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div className="input-group">
                  <label className="input-label">Workflow Name</label>
                  <input
                    className="input-field"
                    type="text"
                    placeholder="e.g., daily_report"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </div>
                <div className="input-group">
                  <label className="input-label">Steps (JSON array)</label>
                  <textarea
                    className="input-field input-mono"
                    placeholder={'[\n  { "name": "fetch_data", "action": "web_search", "depends_on": [] },\n  { "name": "summarize", "action": "send_message", "depends_on": ["fetch_data"] }\n]'}
                    value={newSteps}
                    onChange={(e) => setNewSteps(e.target.value)}
                    style={{ minHeight: 100, resize: 'vertical', fontFamily: 'var(--font-mono)', fontSize: 12 }}
                  />
                </div>
                <button
                  className="btn btn-primary"
                  onClick={handleCreate}
                  disabled={!newName.trim() || creating}
                >
                  {creating ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Creating...</> : 'Create Workflow'}
                </button>
              </div>
            )}
          </div>

          {/* Workflow List */}
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Workflows ({workflows.length})</span>
              <button className="btn btn-ghost btn-sm" onClick={loadWorkflows}>Refresh</button>
            </div>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>
                <span className="spinner" style={{ width: 20, height: 20 }} /> Loading...
              </div>
            ) : workflows.length === 0 ? (
              <div className="empty-state" style={{ padding: 24 }}>
                <span className="empty-icon">⚡</span>
                <h3>No Workflows</h3>
                <p>Create your first workflow above or via chat commands.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {workflows.map((wf) => (
                  <div key={wf.id} style={{
                    padding: '12px 14px', background: 'var(--bg-tertiary)',
                    borderRadius: 'var(--radius-sm)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div>
                        <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>{wf.name}</span>
                        <span style={{
                          marginLeft: 8, fontSize: 11, padding: '2px 8px',
                          borderRadius: 10, background: statusColor(wf.status) + '22',
                          color: statusColor(wf.status), fontWeight: 600,
                        }}>
                          {wf.status}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {wf.status !== 'running' ? (
                          <button className="btn btn-primary btn-sm" onClick={() => handleRun(wf.id)}>Run</button>
                        ) : (
                          <button className="btn btn-secondary btn-sm" onClick={() => handlePause(wf.id)}>Pause</button>
                        )}
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(wf.id)}>Delete</button>
                      </div>
                    </div>
                    {wf.steps && wf.steps.length > 0 && (
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {wf.steps.map((step, i) => (
                          <div key={step.id || i} style={{
                            fontSize: 11, padding: '3px 8px',
                            borderRadius: 4, background: 'var(--bg-secondary)',
                            color: statusColor(step.status),
                            border: `1px solid ${statusColor(step.status)}33`,
                          }}>
                            {step.name}
                          </div>
                        ))}
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6, display: 'flex', gap: 12 }}>
                      {wf.steps && <span>{wf.steps.length} step(s)</span>}
                      {wf.last_run && <span>Last run: {new Date(wf.last_run).toLocaleString()}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Chat Commands Reference */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Chat Commands</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
              {[
                ['create workflow "name" with steps...', 'Create a new workflow'],
                ['run workflow "name"', 'Execute a workflow'],
                ['pause workflow "name"', 'Pause a running workflow'],
                ['show workflow status', 'Check workflow progress'],
                ['list workflows', 'Show all workflows'],
              ].map(([cmd, desc]) => (
                <div key={cmd} style={{ display: 'flex', gap: 12, padding: '6px 0' }}>
                  <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-blue)', minWidth: 300 }}>{cmd}</code>
                  <span style={{ color: 'var(--text-muted)' }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
