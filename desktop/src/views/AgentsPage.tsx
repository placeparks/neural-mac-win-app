// NeuralClaw Desktop — Agents Page
// Multi-agent orchestration: create, manage, and monitor sub-agents

import { useState, useEffect, useCallback } from 'react';
import Header from '../components/layout/Header';
import AgentCard from '../components/agents/AgentCard';
import AgentCreateForm from '../components/agents/AgentCreateForm';
import AgentActivityFeed from '../components/agents/AgentActivityFeed';
import DelegateTaskModal from '../components/agents/DelegateTaskModal';
import { useAgentStore } from '../store/agentStore';
import { AgentDefinition } from '../lib/api';
import { updateAgentDefinition } from '../lib/api';

export default function AgentsPage() {
  const {
    definitions, running, loading,
    loadAll, createAgent, deleteAgent, spawnAgent, despawnAgent,
  } = useAgentStore();

  const [showCreate, setShowCreate] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentDefinition | null>(null);
  const [showDelegate, setShowDelegate] = useState(false);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Auto-refresh running agents every 5s
  useEffect(() => {
    const timer = setInterval(() => useAgentStore.getState().loadRunning(), 5000);
    return () => clearInterval(timer);
  }, []);

  const handleSave = useCallback(async (data: Partial<AgentDefinition>) => {
    if (editingAgent) {
      await updateAgentDefinition(editingAgent.agent_id, data);
      await loadAll();
      setEditingAgent(null);
    } else {
      const result = await createAgent(data);
      if (result.ok) {
        setShowCreate(false);
      }
    }
  }, [editingAgent, createAgent, loadAll]);

  const handleCancel = () => {
    setShowCreate(false);
    setEditingAgent(null);
  };

  return (
    <>
      <Header title="Agents" />
      <div className="app-content">
        <div className="page-header">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <h1>Agents</h1>
              <p>Create and manage sub-agents with independent providers, models, and memory.</p>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {running.length > 0 && (
                <button
                  className="btn btn-secondary"
                  onClick={() => setShowDelegate(true)}
                  style={{ fontSize: 13 }}
                >
                  Delegate Task
                </button>
              )}
              <button
                className="btn btn-primary"
                onClick={() => { setShowCreate(true); setEditingAgent(null); }}
                style={{ fontSize: 13 }}
              >
                + Create Agent
              </button>
            </div>
          </div>
        </div>

        <div className="page-body">
          {/* Create/Edit Form */}
          {(showCreate || editingAgent) && (
            <div style={{ marginBottom: 20 }}>
              <AgentCreateForm
                initial={editingAgent}
                onSave={handleSave}
                onCancel={handleCancel}
              />
            </div>
          )}

          {/* Agent Grid */}
          {loading && definitions.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <span className="spinner" style={{ width: 24, height: 24 }} />
              <p style={{ color: 'var(--text-muted)', marginTop: 8 }}>Loading agents...</p>
            </div>
          ) : definitions.length === 0 && !showCreate ? (
            <div className="empty-state" style={{ padding: 40 }}>
              <span className="empty-icon" style={{ fontSize: 40 }}>🤖</span>
              <h3>No Agents Yet</h3>
              <p>Create your first sub-agent to get started with multi-agent orchestration.</p>
              <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                + Create Agent
              </button>
            </div>
          ) : (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: 12,
              marginBottom: 24,
            }}>
              {definitions.map((defn) => (
                <AgentCard
                  key={defn.agent_id}
                  definition={defn}
                  running={running.find((r) => r.name === defn.name)}
                  onSpawn={() => spawnAgent(defn.agent_id)}
                  onDespawn={() => despawnAgent(defn.agent_id)}
                  onEdit={() => { setEditingAgent(defn); setShowCreate(false); }}
                  onDelete={() => deleteAgent(defn.agent_id)}
                />
              ))}
            </div>
          )}

          {/* Running Agents / Activity Feed */}
          {running.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
                Running Agents ({running.length})
              </h3>
              <AgentActivityFeed running={running} />
            </div>
          )}
        </div>
      </div>

      {/* Delegate Task Modal */}
      {showDelegate && (
        <DelegateTaskModal
          agents={running}
          onClose={() => setShowDelegate(false)}
        />
      )}
    </>
  );
}
