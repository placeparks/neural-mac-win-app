// NeuralClaw Desktop - Agent Card Component

import { useEffect, useState } from 'react';
import { AgentDefinition, AgentMemorySnapshot, RunningAgent, getAgentMemories } from '../../lib/api';
import { PROVIDER_COLORS } from '../../lib/theme';

interface Props {
  definition: AgentDefinition;
  running: RunningAgent | undefined;
  onSpawn: () => void;
  onDespawn: () => void;
  onTalk: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

export default function AgentCard({ definition, running, onSpawn, onDespawn, onTalk, onEdit, onDelete }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [memories, setMemories] = useState<AgentMemorySnapshot | null>(null);
  const [loadingMemories, setLoadingMemories] = useState(false);

  const isOnline = !!running;
  const providerColor = (PROVIDER_COLORS as Record<string, { bg: string } | undefined>)[definition.provider]?.bg || 'var(--bg-card)';
  const formatEventTime = (value: number) => new Date(value > 1_000_000_000_000 ? value : value * 1000).toLocaleTimeString();

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;
    setLoadingMemories(true);
    getAgentMemories(definition.name)
      .then((snapshot) => {
        if (!cancelled) setMemories(snapshot);
      })
      .catch(() => {
        if (!cancelled) setMemories(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingMemories(false);
      });
    return () => {
      cancelled = true;
    };
  }, [definition.name, expanded]);

  return (
    <div className="card" style={{ padding: 16, position: 'relative' }}>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        style={{
          position: 'absolute',
          top: 12,
          right: 12,
          background: 'transparent',
          border: 'none',
          color: 'var(--text-muted)',
          cursor: 'pointer',
          fontSize: 12,
        }}
      >
        {expanded ? 'Hide' : 'Details'}
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <span
          className={`status-dot ${isOnline ? 'online' : 'offline'}`}
          style={{ width: 10, height: 10, flexShrink: 0 }}
        />
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0, flex: 1 }}>
          {definition.name}
        </h3>
        <span
          className="badge"
          style={{
            background: providerColor,
            fontSize: 11,
            padding: '2px 8px',
            marginRight: 44,
          }}
        >
          {definition.provider}
        </span>
      </div>

      {definition.description && (
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: '0 0 8px 0' }}>
          {definition.description}
        </p>
      )}

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontFamily: 'var(--font-mono)' }}>
        {definition.model || 'No model set'}
      </div>

      {running && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, fontSize: 11, color: 'var(--text-muted)' }}>
          <span className="badge badge-green" style={{ fontSize: 10 }}>
            {running.status}
          </span>
          {running.effective_model && (
            <span className="badge badge-blue" style={{ fontSize: 10 }}>
              {running.effective_model}
            </span>
          )}
          <span>{running.active_tasks} active task{running.active_tasks === 1 ? '' : 's'}</span>
        </div>
      )}

      {definition.capabilities.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 12 }}>
          {definition.capabilities.map((cap) => (
            <span key={cap} className="badge badge-blue" style={{ fontSize: 11 }}>
              {cap}
            </span>
          ))}
        </div>
      )}

      {definition.auto_start && (
        <div style={{ fontSize: 11, color: 'var(--accent-green)', marginBottom: 8 }}>
          Auto-start enabled
        </div>
      )}

      {expanded && (
        <div style={{ borderTop: '1px solid var(--border)', marginTop: 12, paddingTop: 12, marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
            Namespace: {memories?.namespace || definition.memory_namespace || `agent:${definition.name}`}
          </div>

          {loadingMemories ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading recent memories...</div>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              {running && (
                <section>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Execution telemetry</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
                    <div style={{ background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Requested / effective</div>
                      <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                        {running.requested_model || definition.model || 'auto'}
                        {running.effective_model && running.effective_model !== (running.requested_model || definition.model)
                          ? ` -> ${running.effective_model}`
                          : ''}
                      </div>
                    </div>
                    <div style={{ background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Latency / success</div>
                      <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                        {running.avg_latency_ms ? `${running.avg_latency_ms.toFixed(0)} ms` : 'unknown'}
                        {' · '}
                        {running.success_count || 0}/{(running.success_count || 0) + (running.failure_count || 0)}
                      </div>
                    </div>
                    <div style={{ background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Token totals</div>
                      <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                        {running.token_usage?.total ?? 'unknown'}
                      </div>
                    </div>
                    <div style={{ background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Last task</div>
                      <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                        {running.last_task_at ? formatEventTime(running.last_task_at) : 'waiting'}
                      </div>
                    </div>
                  </div>
                  {running.last_error && (
                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--accent-red)', whiteSpace: 'pre-wrap' }}>
                      Last error: {running.last_error}
                    </div>
                  )}
                </section>
              )}

              <section>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Recent episodic memory</div>
                {memories?.episodic?.length ? (
                  <div style={{ display: 'grid', gap: 6 }}>
                    {memories.episodic.slice(0, 3).map((memory) => (
                      <div key={memory.id} style={{ fontSize: 12, color: 'var(--text-secondary)', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{memory.source}</div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{memory.content}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No episodic memories yet.</div>
                )}
              </section>

              <section>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Knowledge graph</div>
                {memories?.semantic?.length ? (
                  <div style={{ display: 'grid', gap: 4 }}>
                    {memories.semantic.slice(0, 4).map((triple, index) => (
                      <div key={`${triple.subject}-${triple.predicate}-${index}`} style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {triple.subject} {triple.predicate} {triple.object}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No semantic facts yet.</div>
                )}
              </section>

              <section>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Learned procedures</div>
                {memories?.procedural?.length ? (
                  <div style={{ display: 'grid', gap: 4 }}>
                    {memories.procedural.slice(0, 3).map((procedure) => (
                      <div key={procedure.id} style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {procedure.name} ({Math.round(procedure.success_rate * 100)}%)
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No stored procedures yet.</div>
                )}
              </section>

              {running?.recent_tasks?.length ? (
                <section>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Recent delegated work</div>
                  <div style={{ display: 'grid', gap: 6 }}>
                    {running.recent_tasks.slice().reverse().map((entry, index) => (
                      <div key={`${entry.timestamp}-${index}`} style={{ fontSize: 12, color: 'var(--text-secondary)', background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', padding: 10 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                          {entry.success ? 'completed' : 'failed'} · {Math.round(entry.latency_ms)} ms
                        </div>
                        <div style={{ marginBottom: 4 }}>{entry.task}</div>
                        <div style={{ color: 'var(--text-muted)' }}>{entry.result_preview}</div>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}

              {running?.recent_logs?.length ? (
                <section>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Execution log</div>
                  <div style={{ display: 'grid', gap: 4 }}>
                    {running.recent_logs.slice().reverse().map((entry, index) => (
                      <div key={`${entry.timestamp}-${index}`} style={{ fontSize: 12, color: entry.level === 'error' ? 'var(--accent-red)' : 'var(--text-secondary)' }}>
                        [{formatEventTime(entry.timestamp)}] {entry.message}
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
        {isOnline ? (
          <button className="btn btn-secondary" onClick={onDespawn} style={{ fontSize: 12, padding: '4px 10px' }}>
            Stop
          </button>
        ) : (
          <button className="btn btn-primary" onClick={onSpawn} style={{ fontSize: 12, padding: '4px 10px' }}>
            Start
          </button>
        )}
        <button className="btn btn-secondary" onClick={onEdit} style={{ fontSize: 12, padding: '4px 10px' }}>
          Edit
        </button>
        <button className="btn btn-secondary" onClick={onTalk} style={{ fontSize: 12, padding: '4px 10px' }}>
          Talk
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => {
            if (confirm(`Delete agent "${definition.name}"?`)) onDelete();
          }}
          style={{ fontSize: 12, padding: '4px 10px', color: 'var(--accent-red)' }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}
