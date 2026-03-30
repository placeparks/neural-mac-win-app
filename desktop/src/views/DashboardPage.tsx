// NeuralClaw Desktop — Dashboard Page
// Uses Dashboard API at :8080/api/stats, /api/bus, /api/agents, etc.

import { useState, useEffect, useCallback } from 'react';
import Header from '../components/layout/Header';
import { getStats, getBusEvents, getAgents, getTraces } from '../lib/api';
import type { StatsResponse, BusEvent, Agent, Trace } from '../lib/api';

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [traces, setTraces] = useState<Trace[]>([]);

  const loadAll = useCallback(async () => {
    try {
      const [s, e, a, t] = await Promise.allSettled([getStats(), getBusEvents(), getAgents(), getTraces(20)]);
      if (s.status === 'fulfilled') setStats(s.value);
      if (e.status === 'fulfilled') setEvents(e.value);
      if (a.status === 'fulfilled') setAgents(a.value);
      if (t.status === 'fulfilled') setTraces(t.value);
    } catch { /* */ }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  return (
    <>
      <Header title="Dashboard" />
      <div className="app-content">
        <div className="page-header">
          <h1>📊 Dashboard</h1>
          <p>Real-time statistics, agent activity, and system health.</p>
        </div>

        <div className="page-body">
          {/* Stats Grid */}
          <div className="stats-grid" style={{ marginBottom: 24 }}>
            <div className="stat-card">
              <div className="stat-label">Provider</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{stats?.provider ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Interactions</div>
              <div className="stat-value">{stats?.interactions ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Success Rate</div>
              <div className="stat-value">
                {stats?.success_rate != null ? `${(stats.success_rate * 100).toFixed(0)}%` : '—'}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Skills Loaded</div>
              <div className="stat-value">{stats?.skills ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Channels</div>
              <div className="stat-value" style={{ fontSize: 14 }}>{stats?.channels ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Uptime</div>
              <div className="stat-value" style={{ fontSize: 16 }}>{stats?.uptime ?? '—'}</div>
            </div>
          </div>

          {/* Agents */}
          {agents.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Swarm Agents</h3>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {agents.map((ag) => (
                  <div key={ag.name} className="badge badge-blue" style={{ padding: '6px 12px' }}>
                    {ag.name} — {ag.status}
                  </div>
                ))}
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
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span className={`badge ${t.category === 'memory' ? 'badge-blue' : t.category === 'reasoning' ? 'badge-purple' : t.category === 'action' ? 'badge-green' : 'badge-orange'}`}>
                        {t.category}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {new Date(t.timestamp * 1000).toLocaleTimeString()}
                      </span>
                    </div>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>{t.message}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state" style={{ padding: 30 }}>
                <span className="empty-icon">📊</span>
                <h3>No Traces Yet</h3>
                <p>Traces will appear here as NeuralClaw processes requests.</p>
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
                  }}>
                    <span style={{ color: 'var(--text-muted)', width: 70 }}>
                      {ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : ''}
                    </span>
                    <span style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>{ev.type}</span>
                    <span style={{ color: 'var(--text-muted)', flex: 1 }}>{ev.source}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{ev.data_preview}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No events yet</p>
            )}
          </div>

          <button className="btn btn-secondary" onClick={loadAll}>
            🔄 Refresh All
          </button>
        </div>
      </div>
    </>
  );
}
