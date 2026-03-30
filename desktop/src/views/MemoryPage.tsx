// NeuralClaw Desktop — Memory Page
// Uses Dashboard API at :8080/api/memory

import { useState, useEffect, useCallback } from 'react';
import Header from '../components/layout/Header';
import { getMemoryStats, clearMemory } from '../lib/api';
import type { MemoryStats } from '../lib/api';

export default function MemoryPage() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(false);

  const loadMemory = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getMemoryStats();
      setStats(data);
    } catch { /* backend might be offline */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadMemory(); }, [loadMemory]);

  const handleClear = async () => {
    if (!confirm('Permanently delete ALL memory? This cannot be undone.')) return;
    try {
      const result = await clearMemory();
      if (result.ok) {
        alert(`Cleared: ${result.episodic_deleted || 0} episodes, ${result.semantic_deleted || 0} entities, ${result.procedural_deleted || 0} procedures`);
        loadMemory();
      }
    } catch { /* */ }
  };

  return (
    <>
      <Header title="Memory Browser" />
      <div className="app-content">
        <div className="page-header">
          <h1>🧠 Memory Browser</h1>
          <p>View memory statistics and manage stored knowledge.</p>
        </div>

        <div className="page-body">
          {loading && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
              <div className="spinner spinner-lg" />
            </div>
          )}

          {!loading && stats && (
            <div className="stats-grid" style={{ marginBottom: 24 }}>
              <div className="stat-card">
                <div className="stat-label">Episodic Episodes</div>
                <div className="stat-value">{stats.episodic_count}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Semantic Entities</div>
                <div className="stat-value">{stats.semantic_count}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Procedures</div>
                <div className="stat-value">{stats.procedural_count}</div>
              </div>
            </div>
          )}

          {!loading && !stats && (
            <div className="empty-state">
              <span className="empty-icon">🧠</span>
              <h3>Memory Offline</h3>
              <p>Connect to the NeuralClaw backend to view memory statistics.</p>
            </div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary" onClick={loadMemory}>🔄 Refresh</button>
            <button className="btn btn-danger" onClick={handleClear}>🗑 Clear All Memory</button>
          </div>
        </div>
      </div>
    </>
  );
}
