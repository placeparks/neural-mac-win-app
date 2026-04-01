// NeuralClaw Desktop - Settings Page

import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { DEFAULT_MODELS, ALL_PROVIDERS } from '../lib/theme';
import type { ProviderId } from '../lib/theme';
import { APP_VERSION } from '../lib/constants';
import { useAvatarState } from '../avatar/useAvatarState';

const SECTIONS = ['General', 'Provider', 'Models', 'Memory', 'Avatar', 'Features', 'Advanced'] as const;

interface FeatureEntry {
  label: string;
  value: boolean;
  live: boolean;
}

export default function SettingsPage() {
  const [section, setSection] = useState<(typeof SECTIONS)[number]>('General');
  const [config, setConfig] = useState<Record<string, any>>({});
  const [features, setFeatures] = useState<Record<string, FeatureEntry>>({});
  const [backend, setBackend] = useState<{ running: boolean; port: number; healthy: boolean } | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const [selProvider, setSelProvider] = useState<ProviderId>('openai');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  const {
    hydrate: hydrateAvatar,
    visible: avatarVisible,
    anchor: avatarAnchor,
    scale: avatarScale,
    modelPath: avatarModelPath,
    toggleVisible,
    setAnchor: setAvatarAnchor,
    setScale: setAvatarScale,
    saveModelFile,
  } = useAvatarState();

  useEffect(() => {
    void hydrateAvatar();

    invoke<string>('get_config').then((result) => {
      try {
        const parsed = JSON.parse(result);
        setConfig(parsed);
        const providers = parsed.providers || {};
        const primary = providers.primary || 'openai';
        const providerId = ALL_PROVIDERS.find((provider) => provider.id === primary)?.id || 'openai';
        setSelProvider(providerId as ProviderId);
        setBaseUrl(providers[primary]?.base_url || '');
      } catch {
        // Ignore malformed config responses.
      }
    }).catch(() => {});

    invoke<string>('get_features').then((result) => {
      try {
        setFeatures(JSON.parse(result));
      } catch {
        // Ignore malformed feature responses.
      }
    }).catch(() => {});

    invoke<{ running: boolean; port: number; healthy: boolean }>('get_backend_status')
      .then(setBackend)
      .catch(() => {});
  }, [hydrateAvatar]);

  const save = async (updates: Record<string, any>) => {
    setSaving(true);
    setMsg(null);
    try {
      await invoke<string>('update_config', { config: updates });
      setConfig((prev) => ({ ...prev, ...updates }));
      setMsg('Saved.');
    } catch {
      setMsg('Failed to save.');
    } finally {
      setSaving(false);
    }
  };

  const toggleFeature = async (key: string, value: boolean) => {
    try {
      await invoke<string>('set_feature', { feature: key, value });
      setFeatures((prev) => ({ ...prev, [key]: { ...prev[key], value } }));
    } catch {
      setMsg('Failed to toggle feature.');
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await invoke<string>('validate_api_key', {
        provider: selProvider,
        apiKey: apiKey || 'test',
        endpoint: baseUrl || undefined,
      });
      const parsed = JSON.parse(result);
      setTestResult(
        parsed.valid
          ? { ok: true, text: 'Connected successfully' }
          : { ok: false, text: 'Invalid API key or unreachable' },
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

  const refreshMemoryStats = () => {
    invoke<string>('get_memory_episodes').then((result) => {
      try {
        setConfig((prev) => ({ ...prev, _memory: JSON.parse(result) }));
      } catch {
        // Ignore malformed memory responses.
      }
    }).catch(() => {});
  };

  return (
    <>
      <Header title="Settings" />
      <div className="settings-layout" style={{ flex: 1, overflow: 'hidden' }}>
        <nav className="settings-nav">
          {SECTIONS.map((entry) => (
            <button
              key={entry}
              className={`settings-nav-item ${section === entry ? 'active' : ''}`}
              onClick={() => {
                setSection(entry);
                setMsg(null);
                setTestResult(null);
              }}
            >
              {entry}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {msg && (
            <div
              className="info-box"
              style={{
                marginBottom: 12,
                background: msg.includes('Failed') ? 'var(--accent-red-muted)' : 'var(--accent-green-muted)',
              }}
            >
              <span className="info-icon">{msg.includes('Failed') ? '!' : '✓'}</span>
              <span>{msg}</span>
            </div>
          )}

          {section === 'General' && (
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
                  defaultValue={config.general?.name || 'NeuralClaw'}
                  onBlur={(event) => {
                    void save({ general: { ...config.general, name: event.target.value } });
                  }}
                />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Log Level</div>
                  <div className="settings-row-desc">Backend logging verbosity</div>
                </div>
                <select
                  className="input-field"
                  style={{ width: 120 }}
                  value={config.general?.log_level || 'INFO'}
                  onChange={(event) => {
                    void save({ general: { ...config.general, log_level: event.target.value } });
                  }}
                >
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

          {section === 'Provider' && (
            <div className="settings-section">
              <h2>AI Provider</h2>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="input-group" style={{ marginBottom: 16 }}>
                  <label className="input-label">Primary Provider</label>
                  <select
                    className="input-field"
                    value={selProvider}
                    onChange={(event) => {
                      const id = event.target.value as ProviderId;
                      setSelProvider(id);
                      setTestResult(null);
                      const providerConfig = config.providers?.[id] || {};
                      setBaseUrl(providerConfig.base_url || '');
                    }}
                  >
                    {ALL_PROVIDERS.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name} ({provider.company})
                      </option>
                    ))}
                  </select>
                </div>

                {selProvider !== 'local' && selProvider !== 'meta' && (
                  <div className="input-group" style={{ marginBottom: 16 }}>
                    <label className="input-label">API Key</label>
                    <input
                      className="input-field input-mono"
                      type="password"
                      placeholder="Enter API key..."
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                    />
                  </div>
                )}

                <div className="input-group">
                  <label className="input-label">Base URL</label>
                  <input
                    className="input-field input-mono"
                    placeholder={selProvider === 'local' ? 'http://localhost:11434/v1' : 'https://api.openai.com/v1'}
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                  />
                </div>

                {testResult && (
                  <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className={`status-dot ${testResult.ok ? 'online' : 'offline'}`} />
                    <span style={{ fontSize: 13, color: testResult.ok ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {testResult.text}
                    </span>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-secondary" onClick={() => { void testConnection(); }} disabled={testing}>
                  {testing ? 'Testing...' : 'Test Connection'}
                </button>
                <button className="btn btn-primary" disabled={saving} onClick={() => { void saveProvider(); }}>
                  {saving ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          )}

          {section === 'Models' && (
            <div className="settings-section">
              <h2>Models</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Available models by provider. The primary model is used for reasoning.
              </p>

              {config.model_roles?.enabled && (
                <div className="info-box" style={{ marginBottom: 16, background: 'var(--accent-green-muted)' }}>
                  <span className="info-icon">✓</span>
                  <span>Role-based routing active. Models are selected by call-site role.</span>
                </div>
              )}

              {(Object.keys(DEFAULT_MODELS) as ProviderId[]).map((providerId) => (
                <div key={providerId} className="card" style={{ marginBottom: 12 }}>
                  <div className="card-header">
                    <span className="card-title">{ALL_PROVIDERS.find((provider) => provider.id === providerId)?.name || providerId}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {DEFAULT_MODELS[providerId].map((model) => (
                      <div
                        key={model.name}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '8px 12px',
                          background: 'var(--bg-tertiary)',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: 13,
                        }}
                      >
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

          {section === 'Memory' && (
            <div className="settings-section">
              <h2>Memory</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                NeuralClaw uses episodic, semantic, and procedural memory systems.
              </p>
              <div className="card" style={{ marginBottom: 12 }}>
                <div className="card-header">
                  <span className="card-title">Memory Statistics</span>
                  <button className="btn btn-ghost btn-sm" onClick={refreshMemoryStats}>Refresh</button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                  {['episodic', 'semantic', 'procedural'].map((type) => (
                    <div
                      key={type}
                      style={{
                        padding: 12,
                        background: 'var(--bg-tertiary)',
                        borderRadius: 'var(--radius-sm)',
                        textAlign: 'center',
                      }}
                    >
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
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      const value = (document.getElementById('mem-search') as HTMLInputElement | null)?.value;
                      if (value) invoke<string>('search_memory', { query: value }).catch(() => {});
                    }}
                  >
                    Search
                  </button>
                </div>
              </div>
              <div style={{ marginTop: 16 }}>
                <button
                  className="btn btn-danger"
                  onClick={() => {
                    if (confirm('Clear all memory? This cannot be undone.')) {
                      invoke('clear_chat')
                        .then(() => setMsg('Memory cleared.'))
                        .catch(() => setMsg('Failed to clear memory.'));
                    }
                  }}
                >
                  Clear All Memory
                </button>
              </div>
            </div>
          )}

          {section === 'Avatar' && (
            <div className="settings-section">
              <h2>Avatar</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Floating desktop companion with drag-to-move, chat bubble, and customizable model.
              </p>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Avatar Mode</div>
                    <div className="settings-row-desc">Show or hide the floating avatar window</div>
                  </div>
                  <button className={`toggle ${avatarVisible ? 'on' : ''}`} onClick={() => { void toggleVisible(); }} />
                </div>

                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Anchor Position</div>
                    <div className="settings-row-desc">Snap to a corner, the taskbar, or leave free-floating</div>
                  </div>
                  <select
                    className="input-field"
                    style={{ width: 180 }}
                    value={avatarAnchor}
                    onChange={(event) => { void setAvatarAnchor(event.target.value as any); }}
                  >
                    <option value="bottom-right">Bottom Right</option>
                    <option value="bottom-left">Bottom Left</option>
                    <option value="top-right">Top Right</option>
                    <option value="top-left">Top Left</option>
                    <option value="taskbar">Taskbar</option>
                    <option value="free">Free</option>
                  </select>
                </div>

                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Scale</div>
                    <div className="settings-row-desc">Resize the avatar from 0.5x to 2.0x</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: 220 }}>
                    <input
                      type="range"
                      min="0.5"
                      max="2"
                      step="0.1"
                      value={avatarScale}
                      onChange={(event) => { void setAvatarScale(Number(event.target.value)); }}
                      style={{ flex: 1 }}
                    />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{avatarScale.toFixed(1)}x</span>
                  </div>
                </div>

                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Custom VRM Model</div>
                    <div className="settings-row-desc">Upload a `.vrm` file or keep using the built-in mascot</div>
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    <input
                      type="file"
                      accept=".vrm"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void saveModelFile(file);
                      }}
                    />
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 260 }}>
                      {avatarModelPath || 'Built-in procedural avatar'}
                    </span>
                  </div>
                </div>

                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Preview Thumbnail</div>
                    <div className="settings-row-desc">Current avatar selection preview</div>
                  </div>
                  <div
                    style={{
                      width: 88,
                      height: 88,
                      borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--border)',
                      background: 'radial-gradient(circle at 35% 25%, rgba(114,248,255,0.35), rgba(47,129,247,0.08) 55%, rgba(13,17,23,0.95) 100%)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 28,
                    }}
                  >
                    {avatarModelPath ? 'VRM' : '🤖'}
                  </div>
                </div>
              </div>
            </div>
          )}

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
                Object.entries(features).map(([key, feature]) => (
                  <div key={key} className="settings-row">
                    <div>
                      <div className="settings-row-label">{feature.label || key}</div>
                      <div className="settings-row-desc">
                        {feature.live
                          ? <span className="badge badge-green" style={{ fontSize: 10 }}>● Live</span>
                          : <span className="badge" style={{ fontSize: 10 }}>○ Restart Required</span>}
                      </div>
                    </div>
                    <button className={`toggle ${feature.value ? 'on' : ''}`} onClick={() => { void toggleFeature(key, !feature.value); }} />
                  </div>
                ))
              )}
            </div>
          )}

          {section === 'Advanced' && (
            <div className="settings-section">
              <h2>Advanced</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Backend Sidecar</div>
                  <div className="settings-row-desc">
                    Status:{' '}
                    {backend?.running
                      ? <span style={{ color: 'var(--accent-green)' }}>Running on port {backend.port}</span>
                      : <span style={{ color: 'var(--accent-red)' }}>Stopped</span>}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={async () => {
                      try {
                        await invoke('start_backend');
                        setMsg('Backend started.');
                      } catch {
                        setMsg('Failed to start.');
                      }
                    }}
                  >
                    Start
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={async () => {
                      try {
                        await invoke('stop_backend');
                        setMsg('Backend stopped.');
                      } catch {
                        setMsg('Failed to stop.');
                      }
                    }}
                  >
                    Stop
                  </button>
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
                <button
                  className="btn btn-danger"
                  onClick={() => {
                    if (confirm('Reset all local data? This clears cached settings.')) {
                      localStorage.clear();
                      window.location.reload();
                    }
                  }}
                >
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
