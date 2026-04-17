// NeuralClaw Desktop — Agents Page
// Multi-agent orchestration: create, manage, and monitor sub-agents

import { useState, useEffect, useCallback } from 'react';
import Header from '../components/layout/Header';
import AgentCard from '../components/agents/AgentCard';
import AgentCreateForm from '../components/agents/AgentCreateForm';
import AgentActivityFeed from '../components/agents/AgentActivityFeed';
import DelegateTaskModal from '../components/agents/DelegateTaskModal';
import { useAgentStore } from '../store/agentStore';
import {
  AgentDefinition,
  createDesktopChatSessionWithMetadata,
  getProviderDefaults,
  updateAgentDefinition,
} from '../lib/api';

export default function AgentsPage() {
  const {
    definitions, running, loading, error,
    loadAll, createAgent, deleteAgent, spawnAgent, despawnAgent, clearError,
  } = useAgentStore();

  const [showCreate, setShowCreate] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentDefinition | null>(null);
  const [showDelegate, setShowDelegate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Auto-refresh running agents every 5s
  useEffect(() => {
    const timer = setInterval(() => useAgentStore.getState().loadRunning(), 5000);
    return () => clearInterval(timer);
  }, []);

  const handleSave = useCallback(async (data: Partial<AgentDefinition>) => {
    setSaving(true);
    clearError();
    setFormError(null);
    if (editingAgent) {
      const result = await updateAgentDefinition(editingAgent.agent_id, data);
      if (result.ok) {
        await loadAll();
        setEditingAgent(null);
      } else {
        setFormError(result.error || 'Failed to update agent');
      }
    } else {
      const result = await createAgent(data);
      if (result.ok) {
        await loadAll();
        setShowCreate(false);
      } else {
        setFormError(result.error || 'Failed to create agent');
      }
    }
    setSaving(false);
  }, [clearError, createAgent, editingAgent, loadAll]);

  const handleCancel = () => {
    clearError();
    setFormError(null);
    setShowCreate(false);
    setEditingAgent(null);
  };

  const handleTalkToAgent = async (definition: AgentDefinition) => {
    let resolvedProvider = definition.provider || '';
    let baseUrl = definition.base_url || '';
    if (!resolvedProvider || !baseUrl) {
      try {
        const defaults = await getProviderDefaults(resolvedProvider || 'primary');
        resolvedProvider = resolvedProvider || defaults.provider || defaults.primary;
        baseUrl = baseUrl || defaults.baseUrl || '';
      } catch {
        // Keep the persisted definition values if config lookup fails.
      }
    }
    await createDesktopChatSessionWithMetadata(`Agent: ${definition.name}`, {
      targetAgent: definition.name,
      selectedProvider: resolvedProvider || null,
      selectedModel: definition.model || null,
      baseUrl: baseUrl || null,
    });
    window.dispatchEvent(new CustomEvent('neuralclaw:navigate', { detail: 'chat' }));
  };

  return (
    <>
      <Header title="Agents" />
      <div className="app-content">
        <div className="page-header">
          <div className="page-header-row">
            <div>
              <h1>Agents</h1>
              <p>Create and manage sub-agents with independent providers, models, and memory.</p>
            </div>
            <div className="page-actions">
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
          <div className="info-box" style={{ marginBottom: 16 }}>
            <span className="info-icon">i</span>
            <span>
              Use persistent agents for repeatable roles like reviewer, researcher, builder, or operator. Create the role first, spawn it when needed, then delegate work from here so the Tasks inbox can track execution, approvals, and follow-ups.
            </span>
          </div>

          <div className="workspace-guide-grid" style={{ marginBottom: 16 }}>
            <div className="workspace-guide-card">
              <div className="workspace-guide-title">1. Define the role</div>
              <p>Give each agent a narrow job, strong capability tags, and a model/provider that fits the work instead of making every worker a generic generalist.</p>
            </div>
            <div className="workspace-guide-card">
              <div className="workspace-guide-title">2. Spawn when active</div>
              <p>Saved definitions are durable blueprints. Running agents are the live workforce you can talk to directly or route through delegation modes.</p>
            </div>
            <div className="workspace-guide-card">
              <div className="workspace-guide-title">3. Delegate through Tasks</div>
              <p>Use manual mode for a known owner, pipeline for staged handoffs, consensus for risky decisions, and auto-route when the system should choose.</p>
            </div>
          </div>

          {/* Create/Edit Form */}
          {(showCreate || editingAgent) && (
            <div style={{ marginBottom: 20 }}>
              <AgentCreateForm
                initial={editingAgent}
                saving={saving}
                error={formError || error}
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
                  onTalk={() => { void handleTalkToAgent(defn); }}
                  onEdit={() => { setEditingAgent(defn); setShowCreate(false); }}
                  onDelete={() => deleteAgent(defn.agent_id)}
                />
              ))}
            </div>
          )}

          {/* Running Agents / Activity Feed */}
          {running.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="info-box" style={{ marginBottom: 12 }}>
                <span className="info-icon">i</span>
                <span>
                  Running agents are your live workforce. Talk to one directly for a focused thread, or use delegation when you want durable execution records and orchestration across multiple agents.
                </span>
              </div>
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
