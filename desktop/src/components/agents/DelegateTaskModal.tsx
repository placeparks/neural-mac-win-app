// NeuralClaw Desktop - Delegate Task Modal

import { useState } from 'react';
import {
  RunningAgent,
  createDesktopChatSessionWithMetadata,
  createSharedTask,
  delegateTask,
  getChatBootstrap,
  getProviderDefaults,
  getSharedTask,
  saveDesktopChatMessage,
  switchDesktopChatSession,
  type ChatMessage,
} from '../../lib/api';

interface Props {
  agents: RunningAgent[];
  onClose: () => void;
}

export default function DelegateTaskModal({ agents, onClose }: Props) {
  const [selectedAgents, setSelectedAgents] = useState<string[]>(agents[0]?.name ? [agents[0].name] : []);
  const [task, setTask] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const [sharedTaskDetails, setSharedTaskDetails] = useState<string | null>(null);
  const [useSharedTask, setUseSharedTask] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildResultContent = (
    delegatedTask: string,
    delegatedAgents: string[],
    response: Awaited<ReturnType<typeof delegateTask>>,
  ) => {
    const header = delegatedAgents.length === 1
      ? `Delegated task completed by ${delegatedAgents[0]}.`
      : `Delegated task completed across ${delegatedAgents.join(', ')}.`;
    const details = response.results?.length
      ? response.results
        .map((entry) => {
          const body = entry.result || entry.error || entry.status;
          return `### ${entry.agent}\nStatus: ${entry.status}\n\n${body}`;
        })
        .join('\n\n')
      : (response.result || response.error || 'No response returned.');
    return `${header}\n\nTask:\n${delegatedTask}\n\n${details}`.trim();
  };

  const promptDelegationResult = async (
    delegatedTask: string,
    delegatedAgents: string[],
    response: Awaited<ReturnType<typeof delegateTask>>,
  ) => {
    const defaults = await getProviderDefaults('local').catch(() => ({
      provider: 'local',
      primary: 'local',
      baseUrl: 'http://localhost:11434/v1',
      model: '',
    }));
    const taskMessage: ChatMessage = {
      role: 'user',
      content: delegatedTask,
      timestamp: new Date().toISOString(),
    };
    const assistantMessage: ChatMessage = {
      role: 'assistant',
      content: buildResultContent(delegatedTask, delegatedAgents, response),
      timestamp: new Date().toISOString(),
    };

    let sessionId = '';
    if (delegatedAgents.length === 1) {
      const bootstrap = await getChatBootstrap();
      const existing = bootstrap.sessions.find((session) => session.metadata?.targetAgent === delegatedAgents[0]);
      if (existing) {
        sessionId = existing.sessionId;
        await switchDesktopChatSession(existing.sessionId);
      } else {
        const created = await createDesktopChatSessionWithMetadata(`Agent: ${delegatedAgents[0]}`, {
          targetAgent: delegatedAgents[0],
          selectedProvider: 'local',
          selectedModel: defaults.model || null,
          baseUrl: defaults.baseUrl || 'http://localhost:11434/v1',
        });
        sessionId = created.activeSessionId;
      }
    } else {
      const created = await createDesktopChatSessionWithMetadata(
        `Delegation: ${delegatedAgents.join(', ')}`,
        {
          selectedProvider: 'local',
          selectedModel: defaults.model || null,
          baseUrl: defaults.baseUrl || 'http://localhost:11434/v1',
        },
      );
      sessionId = created.activeSessionId;
    }

    await saveDesktopChatMessage(sessionId, taskMessage);
    await saveDesktopChatMessage(sessionId, assistantMessage);
    window.dispatchEvent(new CustomEvent('neuralclaw:navigate', { detail: 'chat' }));
  };

  const toggleAgent = (agentName: string) => {
    setSelectedAgents((current) =>
      current.includes(agentName)
        ? current.filter((name) => name !== agentName)
        : [...current, agentName],
    );
  };

  const handleDelegate = async () => {
    if (!selectedAgents.length || !task.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setSharedTaskDetails(null);

    try {
      let sharedTaskId: string | undefined;
      if (useSharedTask && selectedAgents.length > 1) {
        const sharedTask = await createSharedTask(selectedAgents);
        if (!sharedTask.ok || !sharedTask.task_id) {
          setError(sharedTask.error || 'Failed to create shared task');
          setLoading(false);
          return;
        }
        sharedTaskId = sharedTask.task_id;
      }

      const res = await delegateTask(selectedAgents[0] || '', task, {
        agentNames: selectedAgents,
        sharedTaskId,
      });

      if (res.ok) {
        const lines = res.results?.length
          ? res.results.map((entry) => `[${entry.agent}] ${entry.result || entry.error || entry.status}`).join('\n\n')
          : (res.result || 'Task completed');
        setResult(lines);

        if (res.shared_task_id) {
          const sharedTask = await getSharedTask(res.shared_task_id);
          if (sharedTask.ok) {
            const details = sharedTask.memories
              .slice(0, 6)
              .map((memory) => `${memory.from_agent}: ${memory.content}`)
              .join('\n');
            setSharedTaskDetails(details || 'Shared task created. No shared memories yet.');
          }
        }

        await promptDelegationResult(task.trim(), selectedAgents, res);
        setLoading(false);
        onClose();
        return;
      } else {
        setError(res.error || 'Delegation failed');
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to delegate');
    }

    setLoading(false);
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="card" style={{ padding: 24, width: 560, maxHeight: '80vh', overflow: 'auto' }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Delegate Task to Agents</h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 8 }}>Target agent(s)</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {agents.map((agent) => {
                const selected = selectedAgents.includes(agent.name);
                return (
                  <button
                    key={agent.name}
                    type="button"
                    className={`btn ${selected ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => toggleAgent(agent.name)}
                    style={{ fontSize: 12, padding: '6px 10px' }}
                  >
                    {agent.name}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Task</label>
            <textarea
              className="input-field"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Describe the task for these agents..."
              rows={4}
              style={{ resize: 'vertical' }}
            />
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
            <input
              type="checkbox"
              checked={useSharedTask}
              onChange={(e) => setUseSharedTask(e.target.checked)}
              disabled={selectedAgents.length < 2}
            />
            Create shared task namespace for collaboration
          </label>

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-primary"
              onClick={handleDelegate}
              disabled={loading || !task.trim() || selectedAgents.length === 0}
            >
              {loading ? 'Delegating...' : 'Delegate'}
            </button>
            <button className="btn btn-secondary" onClick={onClose}>Close</button>
          </div>

          {result && (
            <div style={{
              padding: 12, background: 'var(--accent-green-muted)',
              borderRadius: 'var(--radius-sm)', fontSize: 13,
              border: '1px solid rgba(63,185,80,0.3)',
            }}>
              <strong>Result:</strong>
              <p style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{result}</p>
            </div>
          )}

          {sharedTaskDetails && (
            <div style={{
              padding: 12, background: 'var(--accent-blue-muted)',
              borderRadius: 'var(--radius-sm)', fontSize: 13,
              border: '1px solid rgba(47,129,247,0.25)',
            }}>
              <strong>Shared task memory:</strong>
              <p style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap' }}>{sharedTaskDetails}</p>
            </div>
          )}

          {error && (
            <div style={{
              padding: 12, background: 'var(--accent-red-muted)',
              borderRadius: 'var(--radius-sm)', fontSize: 13, color: 'var(--accent-red)',
              border: '1px solid rgba(248,81,73,0.3)',
            }}>
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
