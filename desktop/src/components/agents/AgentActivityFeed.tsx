// NeuralClaw Desktop - Agent Activity Feed

import { useEffect, useState } from 'react';
import { AgentActivityEvent, RunningAgent, getAgentActivity } from '../../lib/api';

interface Props {
  running: RunningAgent[];
}

const AGENT_COLORS = [
  'var(--accent-blue)',
  'var(--accent-green)',
  'var(--accent-purple)',
  'var(--accent-orange)',
  'var(--accent-cyan)',
  'var(--accent-red)',
];

export default function AgentActivityFeed({ running }: Props) {
  const [events, setEvents] = useState<AgentActivityEvent[]>([]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const next = await getAgentActivity(24);
        if (!cancelled) {
          setEvents(next.filter((event) => event.from_agent && event.to_agent));
        }
      } catch {
        if (!cancelled) setEvents([]);
      }
    };

    load();
    const timer = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (running.length === 0) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        No agents running. Create and start an agent to see activity here.
      </div>
    );
  }

  const colorForAgent = (agentName: string) => {
    const index = Math.max(
      0,
      running.findIndex((agent) => agent.name === agentName),
    );
    return AGENT_COLORS[index % AGENT_COLORS.length];
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {running.map((agent) => (
          <div
            key={agent.name}
            style={{
              padding: '8px 12px',
              background: 'var(--bg-card)',
              borderRadius: 'var(--radius-sm)',
              borderLeft: `3px solid ${colorForAgent(agent.name)}`,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <span className={`status-dot ${agent.status === 'offline' ? 'offline' : 'online'}`} style={{ width: 8, height: 8 }} />
            <span style={{ fontWeight: 600, fontSize: 13 }}>{agent.name}</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{agent.active_tasks} active</span>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gap: 6 }}>
        {events.length === 0 ? (
          <div style={{ padding: 12, color: 'var(--text-muted)', fontSize: 12, background: 'var(--bg-card)', borderRadius: 'var(--radius-sm)' }}>
            Waiting for mesh traffic.
          </div>
        ) : (
          events.slice().reverse().map((event) => (
            <div
              key={event.id}
              style={{
                padding: '10px 12px',
                background: 'var(--bg-card)',
                borderRadius: 'var(--radius-sm)',
                borderLeft: `3px solid ${colorForAgent(event.from_agent)}`,
                display: 'grid',
                gap: 4,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>
                  {event.from_agent} {'->'} {event.to_agent}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {new Date(event.timestamp * 1000).toLocaleTimeString()}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>
                {event.content || event.message_type}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
