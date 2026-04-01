// NeuralClaw Desktop — Settings Page (v1.2.0 — fully wired)

import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { DEFAULT_MODELS, ALL_PROVIDERS } from '../lib/theme';
import type { ProviderId } from '../lib/theme';
import { APP_VERSION } from '../lib/constants';

const SECTIONS = ['General', 'Provider', 'Models', 'Memory', 'Features', 'Advanced'];

interface FeatureEntry { label: string; value: boolean; live: boolean }

export default function SettingsPage() {
  const [section, setSection] = useState('General');
  const [config, setConfig] = useState<Record<string, any>>({});
  const [features, setFeatures] = useState<Record<string, FeatureEntry>>({});
  const [backend, setBackend] = useState<{ running: boolean; port: number; healthy: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Provider form state
  const [selProvider, setSelProvider] = useState<ProviderId>('openai');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    invoke<string>('get_config').then(r => {
      try {
        const c = JSON.parse(r);
        setConfig(c);
        // Populate provider form from config
        const prov = c.providers || {};
        const primary = prov.primary || 'openai';
        const provId = ALL_PROVIDERS.find(p => p.id === primary)?.id || 'openai';
        setSelProvider(provId as ProviderId);
        setBaseUrl(prov[primary]?.base_url || '');
      } catch {}
    }).catch(() => {});

    invoke<string>('get_features').then(r => {
      try { setFeatures(JSON.parse(r)); } catch {}
    }).catch(() => {});

    invoke<{ running: boolean; port: number; healthy: boolean }>('get_backend_status')
      .then(setBackend).catch(() => {});
  }, []);

  const save = async (updates: Record<string, any>) => {
    setSaving(true);
    setMsg(null);
    try {
      await invoke<string>('update_config', { config: updates });
      setConfig(prev => ({ ...prev, ...updates }));
      setMsg('Saved.');
    } catch {
      setMsg('Failed to save.');
    } finally {
      setSaving(false);
    }
  };

  const toggleFeature = async (key: string, val: boolean) => {
    try {
      await invoke<string>('set_feature', { feature: key, value: val });
      setFeatures(prev => ({ ...prev, [key]: { ...prev[key], value: val } }));
    } catch {
      setMsg('Failed to toggle feature.');
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await invoke<string>('validate_api_key', {
        provider: selProvider,
        apiKey: apiKey || 'test',
        endpoint: baseUrl || undefined,
      });
      const res = JSON.parse(r);
      setTestResult(res.valid
        ? { ok: true, text: 'Connected successfully' }
        : { ok: false, text: 'Invalid API key or unreachable' }
      );
    } catch {
      setTestResult({ ok: false, text: 'Connection failed' });
    } finally {
      setTesting(false);
    }
  };

  const saveProvider = async () => {
    const updates: Record<string, any> = {
      providers: {
        primary: selProvider,
        [selProvider]: {
          ...(config.providers?.[selProvider] || {}),
          base_url: baseUrl,
        },
      },
    };
    await save(updates);
  };

  return (
    <>
      <Header title="Settings" />
      <div className="settings-layout" style={{ flex: 1, overflow: 'hidden' }}>
        <nav className="settings-nav">
          {SECTIONS.map(s => (
            <button key={s} className={`settings-nav-item ${section === s ? 'active' : ''}`}
              onClick={() => { setSection(s); setMsg(null); setTestResult(null); }}>
              {s}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {msg && (
            <div className="info-box" style={{
              marginBottom: 12,
              background: msg.includes('Failed') ? 'var(--accent-red-muted)' : 'var(--accent-green-muted)',
            }}>
              <span className="info-icon">{msg.includes('Failed') ? '!' : '✓'}</span>
              <span>{msg}</span>
            </div>
          )}

          {/* ── GENERAL ── */}
          {section === 'General' && (
            <div className="settings-section">
              <h2>General</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Bot Name</div>
                  <div className="settings-row-desc">The name your AI assistant responds to</div>
                </div>
                <input className="input-field" style={{ width: 200 }}
                  defaultValue={config.general?.name || 'NeuralClaw'}
                  onBlur={e => save({ general: { ...config.general, name: e.target.value } })} />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Log Level</div>
                  <div className="settings-row-desc">Backend logging verbosity</div>
                </div>
                <select className="input-field" style={{ width: 120 }}
                  value={config.general?.log_level || 'INFO'}
                  onChange={e => save({ general: { ...config.general, log_level: e.target.value } })}>
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Desktop Version</div>
                  <div className="settings-row-desc">NeuralClaw Desktop client version</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>v{APP_VERSION}</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Backend Version</div>
                  <div className="settings-row-desc">NeuralClaw gateway engine</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                  {config.version || 'Not connected'}
                </span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Runtime</div>
                  <div className="settings-row-desc">Application framework stack</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>Tauri 2 + React 19</span>
              </div>
            </div>
          )}

          {/* ── PROVIDER ── */}
          {section === 'Provider' && (
            <div className="settings-section">
              <h2>AI Provider</h2>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="input-group" style={{ marginBottom: 16 }}>
                  <label className="input-label">Primary Provider</label>
                  <select className="input-field" value={selProvider}
                    onChange={e => {
                      const id = e.target.value as ProviderId;
                      setSelProvider(id);
                      setTestResult(null);
                      // Load base_url from config for this provider
                      const pConf = config.providers?.[id] || {};
                      setBaseUrl(pConf.base_url || '');
                    }}>
                    {ALL_PROVIDERS.map(p => (
                      <option key={p.id} value={p.id}>{p.name} ({p.company})</option>
                    ))}
                  </select>
                </div>

                {selProvider !== 'local' && selProvider !== 'meta' && (
                  <div className="input-group" style={{ marginBottom: 16 }}>
                    <label className="input-label">API Key</label>
                    <input className="input-field input-mono" type="password"
                      placeholder="Enter API key..."
                      value={apiKey}
                      onChange={e => setApiKey(e.target.value)} />
                  </div>
                )}

                <div className="input-group">
                  <label className="input-label">Base URL</label>
                  <input className="input-field input-mono"
                    placeholder={selProvider === 'local' ? 'http://localhost:11434/v1' : 'https://api.openai.com/v1'}
                    value={baseUrl}
                    onChange={e => setBaseUrl(e.target.value)} />
                </div>

                {testResult && (
                  <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className={'status-dot ' + (testResult.ok ? 'online' : 'offline')} />
                    <span style={{ fontSize: 13, color: testResult.ok ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {testResult.text}
                    </span>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-secondary" onClick={testConnection} disabled={testing}>
                  {testing ? 'Testing...' : 'Test Connection'}
                </button>
                <button className="btn btn-primary" disabled={saving} onClick={saveProvider}>
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          )}

          {/* ── MODELS ── */}
          {section === 'Models' && (
            <div className="settings-section">
              <h2>Models</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Available models by provider. The primary model is used for reasoning.
              </p>

              {/* Role Router Info */}
              {config.model_roles?.enabled && (
                <div className="info-box" style={{ marginBottom: 16, background: 'var(--accent-green-muted)' }}>
                  <span className="info-icon">✓</span>
                  <span>Role-based routing active — models are selected by call-site role (primary/fast/micro/embed)</span>
                </div>
              )}

              {(Object.keys(DEFAULT_MODELS) as ProviderId[]).map(providerId => (
                <div key={providerId} className="card" style={{ marginBottom: 12 }}>
                  <div className="card-header">
                    <span className="card-title">{ALL_PROVIDERS.find(p => p.id === providerId)?.name || providerId}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {DEFAULT_MODELS[providerId].map(model => (
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

          {/* ── MEMORY ── */}
          {section === 'Memory' && (
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
                      try { setConfig(prev => ({ ...prev, _memory: JSON.parse(r) })); } catch {}
                    }).catch(() => {});
                  }}>Refresh</button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                  {['episodic', 'semantic', 'procedural'].map(type => (
                    <div key={type} style={{
                      padding: 12, background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', textAlign: 'center',
                    }}>
                      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {(config._memory as any)?.[`${type}_count`] ?? '—'}
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
                <button className="btn btn-danger" onClick={() => {
                  if (confirm('Clear all memory? This cannot be undone.')) {
                    invoke('clear_chat').then(() => setMsg('Memory cleared.')).catch(() => setMsg('Failed to clear memory.'));
                  }
                }}>
                  Clear All Memory
                </button>
              </div>
            </div>
          )}

          {/* ── FEATURES ── */}
          {section === 'Features' && (
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
                        {feat.live
                          ? <span className="badge badge-green" style={{ fontSize: 10 }}>● Live</span>
                          : <span className="badge" style={{ fontSize: 10 }}>○ Inactive</span>
                        }
                      </div>
                    </div>
                    <button className={`toggle ${feat.value ? 'on' : ''}`}
                      onClick={() => toggleFeature(key, !feat.value)} />
                  </div>
                ))
              )}
            </div>
          )}

          {/* ── ADVANCED ── */}
          {section === 'Advanced' && (
            <div className="settings-section">
              <h2>Advanced</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Backend Sidecar</div>
                  <div className="settings-row-desc">
                    Status: {backend?.running
                      ? <span style={{ color: 'var(--accent-green)' }}>Running on port {backend.port}</span>
                      : <span style={{ color: 'var(--accent-red)' }}>Stopped</span>
                    }
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-primary btn-sm" onClick={async () => {
                    try { await invoke('start_backend'); setMsg('Backend started.'); } catch { setMsg('Failed to start.'); }
                  }}>Start</button>
                  <button className="btn btn-danger btn-sm" onClick={async () => {
                    try { await invoke('stop_backend'); setMsg('Backend stopped.'); } catch { setMsg('Failed to stop.'); }
                  }}>Stop</button>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Dashboard Port</div>
                  <div className="settings-row-desc">REST API port (read-only)</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>8080</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">WebChat Port</div>
                  <div className="settings-row-desc">WebSocket port (read-only)</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>8099</span>
              </div>
              <div style={{ marginTop: 20 }}>
                <button className="btn btn-danger" onClick={() => {
                  if (confirm('Reset all local data? This clears cached settings.')) {
                    localStorage.clear();
                    window.location.reload();
                  }
                }}>
                  Reset All Local Data
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
