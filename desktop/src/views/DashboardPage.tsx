// NeuralClaw Desktop — Dashboard Page
// Uses IPC commands for reliability

import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';

interface Stats {
  provider?: string;
  interactions?: number;
  success_rate?: number;
  skills?: number;
  channels?: string;
  uptime?: string;
}

interface Trace {
  category: string;
  message: string;
  timestamp: number;
}

interface BusEvent {
  type: string;
  source?: string;
  data_preview?: string;
  timestamp?: number;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [health, setHealth] = useState<{ status: string; version?: string; uptime?: string } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = useCallback(async () => {
    setRefreshing(true);
    const results = await Promise.allSettled([
      invoke<string>('get_health'),
      invoke<string>('get_dashboard_stats'),
    ]);

    if (results[0].status === 'fulfilled') {
      try { setHealth(JSON.parse(results[0].value)); } catch { /* */ }
    }
    if (results[1].status === 'fulfilled') {
      try { setStats(JSON.parse(results[1].value)); } catch { /* */ }
    }

    // Try traces and bus events (may not exist)
    try {
      const resp = await fetch('http://127.0.0.1:8080/api/traces?limit=20');
      if (resp.ok) setTraces(await resp.json());
    } catch { /* */ }

    try {
      const resp = await fetch('http://127.0.0.1:8080/api/bus');
      if (resp.ok) setEvents(await resp.json());
    } catch { /* */ }

    setRefreshing(false);
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // Auto-refresh every 10s
  useEffect(() => {
    const timer = setInterval(loadAll, 10000);
    return () => clearInterval(timer);
  }, [loadAll]);

  return (
    <>
      <Header title="Dashboard" />
      <div className="app-content">
        <div className="page-header">
          <h1>📊 Dashboard</h1>
          <p>Real-time statistics, agent activity, and system health.</p>
        </div>

        <div className="page-body">
          {/* Health Banner */}
          {health && (
            <div className="info-box" style={{
              marginBottom: 16,
              background: health.status === 'healthy' ? 'var(--accent-green-muted)' : 'var(--accent-red-muted)',
              borderColor: health.status === 'healthy' ? 'rgba(63,185,80,0.3)' : 'rgba(248,81,73,0.3)',
            }}>
              <span className="info-icon">{health.status === 'healthy' ? '✅' : '⚠️'}</span>
              <span>
                Backend {health.status === 'healthy' ? 'online' : health.status}
                {health.version && ` — v${health.version}`}
                {health.uptime && ` — uptime ${health.uptime}`}
              </span>
            </div>
          )}

          {/* Stats Grid */}
          <div className="stats-grid" style={{ marginBottom: 24 }}>
            <div className="stat-card">
              <div className="stat-label">Provider</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{stats?.provider ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Interactions</div>
              <div className="stat-value">{stats?.interactions ?? 0}</div>
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
              <div className="stat-value" style={{ fontSize: 16 }}>{stats?.uptime || health?.uptime || '—'}</div>
            </div>
          </div>

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
              <div className="empty-state" style={{ padding: 24 }}>
                <span className="empty-icon">📊</span>
                <h3>No Traces Yet</h3>
                <p>Send a message in Chat — traces will appear here as NeuralClaw processes requests.</p>
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
              <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>No events yet — they appear as NeuralClaw processes requests.</p>
            )}
          </div>

          <button className="btn btn-secondary" onClick={loadAll} disabled={refreshing}>
            {refreshing ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Refreshing...</> : '🔄 Refresh All'}
          </button>
        </div>
      </div>
    </>
  );
}
