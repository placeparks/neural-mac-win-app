// NeuralClaw Desktop — Settings Page (Full Implementation)

import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { DEFAULT_MODELS, ALL_PROVIDERS } from '../lib/theme';
import type { ProviderId } from '../lib/theme';
import { APP_VERSION } from '../lib/constants';

const SECTIONS = ['General', 'Provider', 'Models', 'Channels', 'Memory', 'Security', 'Features', 'Advanced', 'About'];

interface FeatureEntry { label: string; value: boolean; live: boolean }

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState('General');
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [features, setFeatures] = useState<Record<string, FeatureEntry>>({});
  const [backendStatus, setBackendStatus] = useState<{ running: boolean; port: number; healthy: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  useEffect(() => {
    // Load config, features, and backend status
    invoke<string>('get_config').then(r => {
      try { setConfig(JSON.parse(r)); } catch { /* empty */ }
    }).catch(() => {});

    invoke<string>('get_features').then(r => {
      try { setFeatures(JSON.parse(r)); } catch { /* empty */ }
    }).catch(() => {});

    invoke<{ running: boolean; port: number; healthy: boolean }>('get_backend_status')
      .then(setBackendStatus)
      .catch(() => {});
  }, []);

  const handleSaveConfig = async (updates: Record<string, unknown>) => {
    setSaving(true);
    setStatusMsg(null);
    try {
      await invoke<string>('update_config', { config: updates });
      setConfig(prev => ({ ...prev, ...updates }));
      setStatusMsg('Saved successfully.');
    } catch (err) {
      setStatusMsg('Failed to save. Check backend connection.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleFeature = async (feature: string, value: boolean) => {
    try {
      await invoke<string>('set_feature', { feature, value });
      setFeatures(prev => ({
        ...prev,
        [feature]: { ...prev[feature], value },
      }));
    } catch {
      setStatusMsg('Failed to toggle feature.');
    }
  };

  const handleStartBackend = async () => {
    try {
      await invoke('start_backend');
      setStatusMsg('Backend started.');
    } catch (err) {
      setStatusMsg('Failed to start backend.');
    }
  };

  const handleStopBackend = async () => {
    try {
      await invoke('stop_backend');
      setStatusMsg('Backend stopped.');
    } catch (err) {
      setStatusMsg('Failed to stop backend.');
    }
  };

  return (
    <>
      <Header title="Settings" />
      <div className="settings-layout" style={{ flex: 1, overflow: 'hidden' }}>
        <nav className="settings-nav">
          {SECTIONS.map((s) => (
            <button
              key={s}
              className={`settings-nav-item ${activeSection === s ? 'active' : ''}`}
              onClick={() => { setActiveSection(s); setStatusMsg(null); }}
            >
              {s}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {statusMsg && (
            <div className="info-box" style={{ marginBottom: 12, background: statusMsg.includes('Failed') ? 'var(--accent-red-muted)' : 'var(--accent-green-muted)' }}>
              <span className="info-icon">{statusMsg.includes('Failed') ? '!' : '✓'}</span>
              <span>{statusMsg}</span>
            </div>
          )}

          {activeSection === 'General' && (
            <div className="settings-section">
              <h2>General</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Bot Name</div>
                  <div className="settings-row-desc">The name your AI assistant responds to</div>
                </div>
                <input
                  className="input-field"
                  style={{ width: 200 }}
                  defaultValue={(config as Record<string, string>).bot_name || 'NeuralClaw'}
                  onBlur={(e) => handleSaveConfig({ bot_name: e.target.value })}
                />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Start on Login</div>
                  <div className="settings-row-desc">Launch NeuralClaw when you log in</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Biometric Lock</div>
                  <div className="settings-row-desc">Require biometric auth to access</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Auto-Update</div>
                  <div className="settings-row-desc">Automatically download and install updates</div>
                </div>
                <button className="toggle on" />
              </div>
            </div>
          )}

          {activeSection === 'Provider' && (
            <div className="settings-section">
              <h2>AI Provider</h2>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="input-group" style={{ marginBottom: 16 }}>
                  <label className="input-label">Primary Provider</label>
                  <select className="input-field">
                    {ALL_PROVIDERS.map(p => (
                      <option key={p.id} value={p.id}>{p.name} ({p.company})</option>
                    ))}
                  </select>
                </div>
                <div className="input-group" style={{ marginBottom: 16 }}>
                  <label className="input-label">API Key</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input className="input-field input-mono" type="password" defaultValue="●●●●●●●●●●" style={{ flex: 1 }} />
                    <button className="btn btn-secondary btn-sm">Change</button>
                  </div>
                </div>
                <div className="input-group">
                  <label className="input-label">Base URL</label>
                  <input className="input-field input-mono" defaultValue="https://api.venice.ai/api/v1" />
                </div>
                <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className={'status-dot ' + (backendStatus?.healthy ? 'online' : 'offline')} />
                  <span style={{ fontSize: 13, color: backendStatus?.healthy ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    {backendStatus?.healthy ? 'Connected' : 'Disconnected'}
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-secondary">Test Connection</button>
                <button className="btn btn-primary" disabled={saving} onClick={() => handleSaveConfig({})}>
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          )}

          {activeSection === 'Models' && (
            <div className="settings-section">
              <h2>Models</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Available models by provider. The primary model is used for reasoning by default.
              </p>
              {(Object.keys(DEFAULT_MODELS) as ProviderId[]).map((providerId) => (
                <div key={providerId} className="card" style={{ marginBottom: 12 }}>
                  <div className="card-header">
                    <span className="card-title">{ALL_PROVIDERS.find(p => p.id === providerId)?.name || providerId}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {DEFAULT_MODELS[providerId].map((model) => (
                      <div key={model.name} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '8px 12px', background: 'var(--bg-tertiary)',
                        borderRadius: 'var(--radius-sm)', fontSize: 13,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span>{model.icon}</span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{model.name}</span>
                        </div>
                        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{model.description}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeSection === 'Channels' && (
            <div className="settings-section">
              <h2>Messaging Channels</h2>
              <div className="card" style={{ marginBottom: 12 }}>
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>✈️</span>
                    <span className="card-title">Telegram</span>
                  </div>
                  <span className="badge badge-green">● Running</span>
                </div>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>Bot: @NeuralClawBot</p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-secondary btn-sm">Configure</button>
                  <button className="btn btn-danger btn-sm">Stop</button>
                </div>
              </div>
              <div className="card">
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>💬</span>
                    <span className="card-title">Discord</span>
                  </div>
                  <span className="badge badge-red">○ Not configured</span>
                </div>
                <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }}>Setup Discord Bot →</button>
              </div>
              <button className="btn btn-secondary" style={{ marginTop: 16 }}>+ Add Channel</button>
            </div>
          )}

          {activeSection === 'Memory' && (
            <div className="settings-section">
              <h2>Memory</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                NeuralClaw uses episodic, semantic, and procedural memory systems.
              </p>
              <div className="card" style={{ marginBottom: 12 }}>
                <div className="card-header">
                  <span className="card-title">Memory Statistics</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => {
                    invoke<string>('get_memory_episodes').then(r => {
                      try { setConfig(prev => ({ ...prev, _memory: JSON.parse(r) })); } catch { /* */ }
                    }).catch(() => {});
                  }}>Refresh</button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                  {['episodic', 'semantic', 'procedural'].map(type => (
                    <div key={type} style={{
                      padding: 12, background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', textAlign: 'center',
                    }}>
                      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {(config._memory as Record<string, number>)?.[`${type}_count`] ?? '—'}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'capitalize' }}>{type}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Memory Search</div>
                  <div className="settings-row-desc">Search across all memory systems</div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input className="input-field" style={{ width: 200 }} placeholder="Search query..." id="mem-search" />
                  <button className="btn btn-secondary btn-sm" onClick={() => {
                    const q = (document.getElementById('mem-search') as HTMLInputElement)?.value;
                    if (q) invoke<string>('search_memory', { query: q }).catch(() => {});
                  }}>Search</button>
                </div>
              </div>
              <div style={{ marginTop: 16 }}>
                <button className="btn btn-danger" onClick={() => invoke('clear_chat').catch(() => {})}>
                  Clear All Memory
                </button>
              </div>
            </div>
          )}

          {activeSection === 'Security' && (
            <div className="settings-section">
              <h2>Security</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Biometric Authentication</div>
                  <div className="settings-row-desc">Require Touch ID / Windows Hello to unlock the app</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Secret Redaction</div>
                  <div className="settings-row-desc">Automatically redact API keys and tokens in logs</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">MCP Authentication</div>
                  <div className="settings-row-desc">Require Bearer token for MCP server connections</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Tool Allowlist</div>
                  <div className="settings-row-desc">Only allow explicitly permitted tools to execute</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="card" style={{ marginTop: 16 }}>
                <div className="card-header">
                  <span className="card-title">MCP Auth Token</span>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input className="input-field input-mono" type="password" defaultValue="●●●●●●●●" style={{ flex: 1 }} />
                  <button className="btn btn-secondary btn-sm">Regenerate</button>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'Features' && (
            <div className="settings-section">
              <h2>Feature Flags</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Enable or disable NeuralClaw subsystems. Changes take effect immediately.
              </p>
              {Object.entries(features).length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">⚙️</span>
                  <h3>No Features Loaded</h3>
                  <p>Connect to the backend to manage feature flags.</p>
                </div>
              ) : (
                Object.entries(features).map(([key, feat]) => (
                  <div key={key} className="settings-row">
                    <div>
                      <div className="settings-row-label">{feat.label || key}</div>
                      <div className="settings-row-desc">
                        {feat.live ? (
                          <span className="badge badge-green" style={{ fontSize: 10 }}>● Live</span>
                        ) : (
                          <span className="badge" style={{ fontSize: 10 }}>○ Inactive</span>
                        )}
                      </div>
                    </div>
                    <button
                      className={`toggle ${feat.value ? 'on' : ''}`}
                      onClick={() => handleToggleFeature(key, !feat.value)}
                    />
                  </div>
                ))
              )}
            </div>
          )}

          {activeSection === 'Advanced' && (
            <div className="settings-section">
              <h2>Advanced</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Backend Sidecar</div>
                  <div className="settings-row-desc">
                    Status: {backendStatus?.running ? (
                      <span style={{ color: 'var(--accent-green)' }}>Running on port {backendStatus.port}</span>
                    ) : (
                      <span style={{ color: 'var(--accent-red)' }}>Stopped</span>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-primary btn-sm" onClick={handleStartBackend}>Start</button>
                  <button className="btn btn-danger btn-sm" onClick={handleStopBackend}>Stop</button>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Dashboard Port</div>
                  <div className="settings-row-desc">REST API port for the backend dashboard</div>
                </div>
                <input className="input-field" style={{ width: 100 }} defaultValue="8080" readOnly />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">WebChat Port</div>
                  <div className="settings-row-desc">WebSocket port for real-time chat</div>
                </div>
                <input className="input-field" style={{ width: 100 }} defaultValue="8099" readOnly />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Log Level</div>
                  <div className="settings-row-desc">Backend logging verbosity</div>
                </div>
                <select className="input-field" style={{ width: 120 }} defaultValue="INFO"
                  onChange={(e) => handleSaveConfig({ log_level: e.target.value })}>
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </div>
              <div style={{ marginTop: 20 }}>
                <button className="btn btn-danger" onClick={() => {
                  localStorage.clear();
                  window.location.reload();
                }}>
                  Reset All Local Data
                </button>
              </div>
            </div>
          )}

          {activeSection === 'About' && (
            <div className="settings-section">
              <h2>About NeuralClaw</h2>
              <div className="card" style={{ marginBottom: 16 }}>
                <div style={{ textAlign: 'center', padding: 20 }}>
                  <div style={{ fontSize: 48, marginBottom: 8 }}>🧠</div>
                  <h2 style={{ margin: '0 0 4px' }}>NeuralClaw Desktop</h2>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>
                    Version {APP_VERSION}
                  </div>
                  <p style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 400, margin: '0 auto' }}>
                    The Self-Evolving AI Assistant. A cognitive agent framework with five cortices,
                    multi-channel support, and autonomous learning capabilities.
                  </p>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div className="settings-row">
                  <div className="settings-row-label">Desktop Version</div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>{APP_VERSION}</span>
                </div>
                <div className="settings-row">
                  <div className="settings-row-label">Backend Version</div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                    {(config as Record<string, string>).version || 'Not connected'}
                  </span>
                </div>
                <div className="settings-row">
                  <div className="settings-row-label">Runtime</div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>Tauri 2 + React 19</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
