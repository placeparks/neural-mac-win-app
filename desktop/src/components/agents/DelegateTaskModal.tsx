// NeuralClaw Desktop - Delegate Task Modal

import { useState } from 'react';
import {
  RunningAgent,
  autoRouteTask,
  createDesktopChatSessionWithMetadata,
  createSharedTask,
  delegateTask,
  getChatBootstrap,
  getPrimaryProviderDefaults,
  getSharedTask,
  pipelineTask,
  saveDesktopChatMessage,
  seekConsensus,
  switchDesktopChatSession,
  type ChatMessage,
  type PipelineStepResult,
} from '../../lib/api';

type DelegationMode = 'manual' | 'auto-route' | 'consensus' | 'pipeline';

interface Props {
  agents: RunningAgent[];
  onClose: () => void;
}

const CONSENSUS_STRATEGIES = [
  { id: 'majority_vote', label: 'Majority Vote' },
  { id: 'best_confidence', label: 'Best Confidence' },
  { id: 'deliberation', label: 'Deliberation (multi-round)' },
];

const MODE_DESCRIPTIONS: Record<DelegationMode, { title: string; detail: string }> = {
  manual: {
    title: 'Direct delegation',
    detail: 'You choose the exact agent or team. Best when you already know who should own the task.',
  },
  pipeline: {
    title: 'Ordered handoff chain',
    detail: 'Each agent picks up where the last one stopped. Best for research -> build -> review flows.',
  },
  'auto-route': {
    title: 'Automatic routing',
    detail: 'NeuralClaw selects the best available agent mix from the current roster.',
  },
  consensus: {
    title: 'Multi-agent agreement',
    detail: 'Several agents answer the same question, then the system compares them to reduce blind spots.',
  },
};

export default function DelegateTaskModal({ agents, onClose }: Props) {
  const [mode, setMode] = useState<DelegationMode>('manual');
  const [selectedAgents, setSelectedAgents] = useState<string[]>(agents[0]?.name ? [agents[0].name] : []);
  const [task, setTask] = useState('');
  const [taskTitle, setTaskTitle] = useState('');
  const [successCriteria, setSuccessCriteria] = useState('');
  const [workspacePath, setWorkspacePath] = useState('');
  const [deliverablesText, setDeliverablesText] = useState('');
  const [integrationTargetsText, setIntegrationTargetsText] = useState('');
  const [executionMode, setExecutionMode] = useState('agent-task');
  const [requireApproval, setRequireApproval] = useState(false);
  const [approvalNote, setApprovalNote] = useState('');
  const [useSharedTask, setUseSharedTask] = useState(false);
  const [consensusStrategy, setConsensusStrategy] = useState('majority_vote');
  const [maxAutoAgents, setMaxAutoAgents] = useState(1);

  const [pipelineAgents, setPipelineAgents] = useState<string[]>(agents.slice(0, 2).map((a) => a.name));

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [sharedTaskDetails, setSharedTaskDetails] = useState<string | null>(null);
  const [consensusDetails, setConsensusDetails] = useState<{ confidence?: number; votes?: { agent: string; response: string; confidence: number }[] } | null>(null);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStepResult[] | null>(null);
  const [routedTo, setRoutedTo] = useState<string[]>([]);
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

  const saveToChat = async (
    delegatedTask: string,
    delegatedAgents: string[],
    resultContent: string,
  ) => {
    try {
      const defaults = await getPrimaryProviderDefaults().catch(() => ({
        provider: 'primary', primary: 'primary', baseUrl: '', model: '',
      }));
      const taskMsg: ChatMessage = { role: 'user', content: delegatedTask, timestamp: new Date().toISOString() };
      const assistantMsg: ChatMessage = { role: 'assistant', content: resultContent, timestamp: new Date().toISOString() };

      let sessionId = '';
      if (delegatedAgents.length === 1) {
        const bootstrap = await getChatBootstrap();
        const existing = bootstrap.sessions.find((s) => s.metadata?.targetAgent === delegatedAgents[0]);
        if (existing) {
          sessionId = existing.sessionId;
          await switchDesktopChatSession(existing.sessionId);
        } else {
          const created = await createDesktopChatSessionWithMetadata(`Agent: ${delegatedAgents[0]}`, {
            targetAgent: delegatedAgents[0],
            selectedProvider: defaults.provider || defaults.primary || null,
            selectedModel: defaults.model || null,
            baseUrl: defaults.baseUrl || null,
          });
          sessionId = created.activeSessionId;
        }
      } else {
        const created = await createDesktopChatSessionWithMetadata(
          `Delegation: ${delegatedAgents.join(', ')}`,
          {
            selectedProvider: defaults.provider || defaults.primary || null,
            selectedModel: defaults.model || null,
            baseUrl: defaults.baseUrl || null,
          },
        );
        sessionId = created.activeSessionId;
      }
      await saveDesktopChatMessage(sessionId, taskMsg);
      await saveDesktopChatMessage(sessionId, assistantMsg);
      window.dispatchEvent(new CustomEvent('neuralclaw:navigate', { detail: 'chat' }));
    } catch {
      // Non-fatal — result still shown in modal
    }
  };

  const toggleAgent = (agentName: string) => {
    setSelectedAgents((cur) =>
      cur.includes(agentName) ? cur.filter((n) => n !== agentName) : [...cur, agentName],
    );
  };

  const deliverables = deliverablesText
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);
  const integrationTargets = integrationTargetsText
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

  const handleDelegate = async () => {
    if (!task.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setSharedTaskDetails(null);
    setConsensusDetails(null);
    setPipelineSteps(null);
    setRoutedTo([]);

    try {
      // ── PIPELINE MODE ────────────────────────────────────────────────────
      if (mode === 'pipeline') {
        const ordered = pipelineAgents.filter(Boolean);
        if (ordered.length < 2) {
          setError('Add at least 2 agents to the pipeline');
          setLoading(false);
          return;
        }
        const enriched = await pipelineTask({
          task,
          agent_names: ordered,
          title: taskTitle.trim() || undefined,
          success_criteria: successCriteria.trim() || undefined,
          deliverables,
          workspace_path: workspacePath.trim() || undefined,
          integration_targets: integrationTargets,
          execution_mode: executionMode,
          require_approval: requireApproval,
          approval_note: approvalNote.trim() || undefined,
        });
        if (!enriched.ok) { setError(enriched.error || 'Pipeline failed'); setLoading(false); return; }
        setPipelineSteps(enriched.pipeline_results || null);
        const finalText = enriched.final_result || enriched.pipeline_results?.slice(-1)[0]?.result || 'Pipeline completed';
        setResult(finalText);
        if (enriched.shared_task_id) {
          const sharedTask = await getSharedTask(enriched.shared_task_id);
          if (sharedTask.ok) {
            setSharedTaskDetails(sharedTask.memories.slice(0, 6).map((m) => `${m.from_agent}: ${m.content}`).join('\n') || 'Pipeline handoffs stored in shared memory.');
          }
        }
        await saveToChat(task.trim(), ordered, `[Pipeline: ${ordered.join(' → ')}]\n\n${finalText}`);
        setLoading(false);
        onClose();
        return;
      }

      // ── AUTO-ROUTE MODE ──────────────────────────────────────────────────
      if (mode === 'auto-route') {
        const routed = await autoRouteTask({
          task,
          max_agents: maxAutoAgents,
          title: taskTitle.trim() || undefined,
          success_criteria: successCriteria.trim() || undefined,
          deliverables,
          workspace_path: workspacePath.trim() || undefined,
          integration_targets: integrationTargets,
          execution_mode: executionMode,
          require_approval: requireApproval,
          approval_note: approvalNote.trim() || undefined,
        });
        if (!routed.ok) { setError(routed.error || 'Auto-route failed'); setLoading(false); return; }

        const targets = routed.routed_to || [];
        setRoutedTo(targets);
        const lines = routed.results?.length
          ? routed.results.map((e) => `[${e.agent}] ${e.result || e.error || e.status}`).join('\n\n')
          : (routed.result || 'Task completed');
        setResult(lines);

        if (routed.shared_task_id) {
          const sharedTask = await getSharedTask(routed.shared_task_id);
          if (sharedTask.ok) {
            setSharedTaskDetails(sharedTask.memories.slice(0, 6).map((m) => `${m.from_agent}: ${m.content}`).join('\n') || 'No shared memories yet');
          }
        }
        await saveToChat(task.trim(), targets, lines);
        setLoading(false);
        onClose();
        return;
      }

      // ── CONSENSUS MODE ───────────────────────────────────────────────────
      if (mode === 'consensus') {
        if (selectedAgents.length < 2) {
          setError('Select at least 2 agents for consensus');
          setLoading(false);
          return;
        }
        const res = await seekConsensus({
          task,
          agent_names: selectedAgents,
          strategy: consensusStrategy,
          title: taskTitle.trim() || undefined,
          success_criteria: successCriteria.trim() || undefined,
          deliverables,
          workspace_path: workspacePath.trim() || undefined,
          integration_targets: integrationTargets,
          execution_mode: executionMode,
          require_approval: requireApproval,
          approval_note: approvalNote.trim() || undefined,
        });
        if (!res.ok) { setError(res.error || 'Consensus failed'); setLoading(false); return; }
        setResult(res.result || 'Consensus reached');
        setConsensusDetails({ confidence: res.confidence, votes: res.agent_responses });
        await saveToChat(task.trim(), selectedAgents, `[Consensus — ${consensusStrategy}]\n\n${res.result || ''}`);
        setLoading(false);
        onClose();
        return;
      }

      // ── MANUAL MODE ──────────────────────────────────────────────────────
      if (!selectedAgents.length) { setError('Select at least one agent'); setLoading(false); return; }

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
        title: taskTitle.trim() || undefined,
        successCriteria: successCriteria.trim() || undefined,
        deliverables,
        workspacePath: workspacePath.trim() || undefined,
        integrationTargets,
        executionMode,
        requireApproval,
        approvalNote: approvalNote.trim() || undefined,
      });
      if (res.ok) {
        const lines = res.results?.length
          ? res.results.map((e) => `[${e.agent}] ${e.result || e.error || e.status}`).join('\n\n')
          : (res.result || 'Task completed');
        setResult(lines);

        if (res.shared_task_id) {
          const sharedTask = await getSharedTask(res.shared_task_id);
          if (sharedTask.ok) {
            setSharedTaskDetails(sharedTask.memories.slice(0, 6).map((m) => `${m.from_agent}: ${m.content}`).join('\n') || 'Shared task created. No shared memories yet.');
          }
        }
        await saveToChat(task.trim(), selectedAgents, buildResultContent(task.trim(), selectedAgents, res));
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

  const modeLabel = mode === 'auto-route' ? 'Auto-Route' : mode === 'consensus' ? 'Seek Consensus' : mode === 'pipeline' ? 'Run Pipeline' : 'Delegate';
  const modeMeta = MODE_DESCRIPTIONS[mode];
  const canSubmit = !loading && task.trim() && (
    mode === 'auto-route' ||
    (mode === 'consensus' && selectedAgents.length >= 2) ||
    (mode === 'pipeline' && pipelineAgents.filter(Boolean).length >= 2) ||
    (mode === 'manual' && selectedAgents.length > 0)
  );

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="card" style={{ padding: 24, width: 580, maxHeight: '85vh', overflow: 'auto' }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Agent Task Delegation</h3>

        {/* Mode Tabs */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
          {(['manual', 'pipeline', 'auto-route', 'consensus'] as DelegationMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              style={{
                padding: '7px 14px', border: 'none', background: 'none', cursor: 'pointer',
                fontSize: 13, fontWeight: mode === m ? 600 : 400,
                color: mode === m ? 'var(--accent)' : 'var(--text-muted)',
                borderBottom: mode === m ? '2px solid var(--accent)' : '2px solid transparent',
                marginBottom: -1,
                textTransform: 'capitalize',
              }}
            >
              {m === 'auto-route' ? 'Auto-Route' : m === 'consensus' ? 'Consensus' : m === 'pipeline' ? 'Pipeline' : 'Manual'}
            </button>
          ))}
        </div>

        <div style={{
          padding: 12,
          borderRadius: 14,
          border: '1px solid rgba(96, 165, 250, 0.18)',
          background: 'rgba(59, 130, 246, 0.08)',
          marginBottom: 16,
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
            {modeMeta.title}
          </div>
          <div style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--text-secondary)' }}>
            {modeMeta.detail}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* Task Input */}
          <div>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Title</label>
            <input
              className="input-field"
              value={taskTitle}
              onChange={(e) => setTaskTitle(e.target.value)}
              placeholder="Optional durable title for the task inbox"
            />
          </div>

          <div>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Task</label>
            <textarea
              className="input-field"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder={
                mode === 'auto-route'
                  ? 'Describe the task — the best available agent will be selected automatically'
                  : mode === 'consensus'
                  ? 'Describe the question or decision — all selected agents will respond and reach consensus'
                  : 'Describe the task for the selected agent(s)...'
              }
              rows={4}
              style={{ resize: 'vertical' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Success Criteria</label>
              <input
                className="input-field"
                value={successCriteria}
                onChange={(e) => setSuccessCriteria(e.target.value)}
                placeholder="What counts as done?"
              />
            </div>
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Workspace Path</label>
              <input
                className="input-field"
                value={workspacePath}
                onChange={(e) => setWorkspacePath(e.target.value)}
                placeholder="Optional repo or project directory"
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 12 }}>
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Deliverables</label>
              <textarea
                className="input-field"
                value={deliverablesText}
                onChange={(e) => setDeliverablesText(e.target.value)}
                placeholder={'One per line: summary\nchanged files\nPR comment'}
                rows={3}
                style={{ resize: 'vertical' }}
              />
            </div>
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Execution Mode</label>
              <select className="input-field" value={executionMode} onChange={(e) => setExecutionMode(e.target.value)}>
                <option value="agent-task">Agent Task</option>
                <option value="workspace-run">Workspace Run</option>
                <option value="integration-loop">Integration Loop</option>
                <option value="review-pass">Review Pass</option>
              </select>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginTop: 10, marginBottom: 4 }}>Integrations</label>
              <input
                className="input-field"
                value={integrationTargetsText}
                onChange={(e) => setIntegrationTargetsText(e.target.value)}
                placeholder="github, slack, google"
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 12, alignItems: 'start' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-secondary)', paddingTop: 8 }}>
              <input
                type="checkbox"
                checked={requireApproval}
                onChange={(e) => setRequireApproval(e.target.checked)}
              />
              Require approval
            </label>
            <div>
              <input
                className="input-field"
                value={approvalNote}
                onChange={(e) => setApprovalNote(e.target.value)}
                placeholder="Optional note shown before execution starts"
                disabled={!requireApproval}
              />
              <p style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                Useful for high-impact runs, external mutations, or business-sensitive workflows.
              </p>
            </div>
          </div>

          {/* Pipeline: ordered agent chain builder */}
          {mode === 'pipeline' && (
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 8 }}>
                Agent Pipeline (ordered — each agent's output feeds the next)
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {pipelineAgents.map((agentName, idx) => (
                  <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', width: 20, textAlign: 'right' }}>{idx + 1}.</span>
                    <select
                      value={agentName}
                      onChange={(e) => {
                        const updated = [...pipelineAgents];
                        updated[idx] = e.target.value;
                        setPipelineAgents(updated);
                      }}
                      style={{ flex: 1, background: 'var(--surface-alt)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px', color: 'inherit', fontSize: 13 }}
                    >
                      <option value="">— select agent —</option>
                      {agents.map((a) => (
                        <option key={a.name} value={a.name}>{a.name}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => {
                        if (idx > 0) {
                          const updated = [...pipelineAgents];
                          [updated[idx - 1], updated[idx]] = [updated[idx], updated[idx - 1]];
                          setPipelineAgents(updated);
                        }
                      }}
                      disabled={idx === 0}
                      title="Move up"
                      style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', color: 'inherit', fontSize: 12, opacity: idx === 0 ? 0.3 : 1 }}
                    >↑</button>
                    <button
                      type="button"
                      onClick={() => {
                        if (idx < pipelineAgents.length - 1) {
                          const updated = [...pipelineAgents];
                          [updated[idx], updated[idx + 1]] = [updated[idx + 1], updated[idx]];
                          setPipelineAgents(updated);
                        }
                      }}
                      disabled={idx === pipelineAgents.length - 1}
                      title="Move down"
                      style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', color: 'inherit', fontSize: 12, opacity: idx === pipelineAgents.length - 1 ? 0.3 : 1 }}
                    >↓</button>
                    <button
                      type="button"
                      onClick={() => setPipelineAgents(pipelineAgents.filter((_, i) => i !== idx))}
                      title="Remove"
                      style={{ background: 'none', border: '1px solid rgba(248,81,73,0.4)', borderRadius: 4, padding: '2px 6px', cursor: 'pointer', color: 'var(--accent-red)', fontSize: 12 }}
                    >✕</button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setPipelineAgents([...pipelineAgents, agents[0]?.name || ''])}
                  style={{ alignSelf: 'flex-start', background: 'none', border: '1px dashed var(--border)', borderRadius: 6, padding: '4px 12px', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 12 }}
                >
                  + Add step
                </button>
              </div>
              <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
                Flow: {pipelineAgents.filter(Boolean).join(' → ') || 'no agents selected'}
              </p>
            </div>
          )}

          {/* Manual / Consensus: agent selection */}
          {mode !== 'auto-route' && mode !== 'pipeline' && (
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 8 }}>
                {mode === 'consensus' ? 'Agents to consult (min. 2)' : 'Target agent(s)'}
              </label>
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
                      {agent.capabilities?.length ? (
                        <span style={{ fontSize: 10, opacity: 0.7, marginLeft: 4 }}>({agent.capabilities.slice(0, 2).join(', ')})</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Auto-Route options */}
          {mode === 'auto-route' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Max agents to use:</label>
              <input
                type="number"
                min={1}
                max={agents.length}
                value={maxAutoAgents}
                onChange={(e) => setMaxAutoAgents(Math.max(1, parseInt(e.target.value) || 1))}
                style={{ width: 60, background: 'var(--surface-alt)', border: '1px solid var(--border)', borderRadius: 6, padding: '4px 8px', color: 'inherit', fontSize: 13 }}
              />
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{agents.length} available</span>
            </div>
          )}

          {/* Consensus options */}
          {mode === 'consensus' && (
            <div>
              <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Consensus Strategy</label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {CONSENSUS_STRATEGIES.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setConsensusStrategy(s.id)}
                    style={{
                      padding: '5px 12px', borderRadius: 20, fontSize: 12,
                      border: `1px solid ${consensusStrategy === s.id ? 'var(--accent)' : 'var(--border)'}`,
                      background: consensusStrategy === s.id ? 'rgba(88,166,255,0.12)' : 'transparent',
                      color: consensusStrategy === s.id ? 'var(--accent)' : 'inherit',
                      cursor: 'pointer',
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Shared task for manual multi-agent */}
          {mode === 'manual' && selectedAgents.length > 1 && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={useSharedTask}
                onChange={(e) => setUseSharedTask(e.target.checked)}
              />
              Create shared task namespace (agents share memory)
            </label>
          )}

          {/* Actions */}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-primary"
              onClick={handleDelegate}
              disabled={!canSubmit}
            >
              {loading ? `${modeLabel}...` : modeLabel}
            </button>
            <button className="btn btn-secondary" onClick={onClose}>Close</button>
          </div>

          {/* Auto-route: show which agents were selected */}
          {routedTo.length > 0 && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Routed to: {routedTo.map((a) => <strong key={a} style={{ color: 'var(--accent)', marginRight: 4 }}>{a}</strong>)}
            </div>
          )}

          {/* Result */}
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

          {/* Consensus breakdown */}
          {consensusDetails && (
            <div style={{
              padding: 12, background: 'var(--accent-blue-muted)',
              borderRadius: 'var(--radius-sm)', fontSize: 13,
              border: '1px solid rgba(47,129,247,0.25)',
            }}>
              <strong>Consensus details</strong>
              {consensusDetails.confidence !== undefined && (
                <span style={{ float: 'right', color: 'var(--text-muted)' }}>
                  confidence: {(consensusDetails.confidence * 100).toFixed(0)}%
                </span>
              )}
              {consensusDetails.votes?.map((v) => (
                <div key={v.agent} style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
                  <span style={{ fontWeight: 600, color: 'var(--accent)' }}>{v.agent}</span>
                  {v.confidence !== undefined && <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>{(v.confidence * 100).toFixed(0)}%</span>}
                  <p style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', color: 'var(--text-secondary)', fontSize: 12 }}>{v.response}</p>
                </div>
              ))}
            </div>
          )}

          {/* Pipeline step-by-step breakdown */}
          {pipelineSteps && pipelineSteps.length > 0 && (
            <div style={{
              padding: 12, background: 'var(--accent-blue-muted)',
              borderRadius: 'var(--radius-sm)', fontSize: 13,
              border: '1px solid rgba(47,129,247,0.25)',
            }}>
              <strong>Pipeline steps</strong>
              {pipelineSteps.map((step, i) => (
                <div key={step.agent + i} style={{ marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: 'var(--accent)' }}>{i + 1}. {step.agent}</span>
                    <span style={{ fontSize: 11, color: step.status === 'completed' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {step.status} · {step.elapsed_seconds}s
                    </span>
                  </div>
                  {step.result && (
                    <p style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', color: 'var(--text-secondary)', fontSize: 12 }}>
                      {step.result.length > 300 ? step.result.slice(0, 300) + '…' : step.result}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Shared task memory */}
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

          {/* Error */}
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
