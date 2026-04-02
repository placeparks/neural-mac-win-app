import { useEffect, useMemo, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { ALL_PROVIDERS, DEFAULT_MODELS, PROVIDER_COLORS, type ProviderId } from '../lib/theme';
import { APP_VERSION } from '../lib/constants';
import { useAvatarState } from '../avatar/useAvatarState';
import {
  clearMemory,
  getChannels,
  getConfig,
  getFeatures,
  getLocalModelHealth,
  getMemoryStats,
  getProviderModels,
  pairChannel,
  resetAllDesktopChatSessions,
  setFeature,
  testChannel,
  updateChannel,
  updateDashboardConfig,
  type ChannelSnapshot,
  type MemoryStats,
  type ModelHealthSnapshot,
  type ModelOption,
} from '../lib/api';

const SECTIONS = ['General', 'Provider', 'Channels', 'Models', 'Memory', 'Avatar', 'Features', 'Advanced'] as const;

const TRUST_MODES = [
  { value: '', label: 'Default' },
  { value: 'open', label: 'Open' },
  { value: 'pair', label: 'Pair' },
  { value: 'bound', label: 'Bound' },
] as const;

const CHANNEL_META: Record<string, { secretLabel: string; placeholder: string; hint: string }> = {
  telegram: {
    secretLabel: 'Bot Token',
    placeholder: '123456:ABCDEF...',
    hint: 'Create the bot in BotFather, then paste the Telegram bot token here.',
  },
  discord: {
    secretLabel: 'Bot Token',
    placeholder: 'discord-bot-token',
    hint: 'Use a Discord bot token with message content intent enabled.',
  },
  slack: {
    secretLabel: 'Bot Token',
    placeholder: 'xoxb-...',
    hint: 'Slack Socket Mode requires the bot token and the app token.',
  },
  whatsapp: {
    secretLabel: 'Auth Directory',
    placeholder: 'C:\\Users\\Lenovo\\.neuralclaw\\sessions\\whatsapp',
    hint: 'This folder stores Baileys session files used for WhatsApp pairing.',
  },
  signal: {
    secretLabel: 'Phone Number',
    placeholder: '+15551234567',
    hint: 'Use the number already registered with signal-cli on this machine.',
  },
};

interface FeatureEntry {
  label: string;
  value: boolean;
  live: boolean;
}

interface ChannelDraft {
  enabled: boolean;
  trust_mode: string;
  secret: string;
  extra: Record<string, unknown>;
}

interface PairPayload {
  authDir?: string;
  qrData?: string;
  qrDataUrl?: string;
  paired?: boolean;
}

function isLocalProvider(provider: string) {
  return provider === 'local' || provider === 'meta';
}

function normalizeDraft(channel: ChannelSnapshot, current?: ChannelDraft): ChannelDraft {
  return {
    enabled: channel.enabled,
    trust_mode: channel.trust_mode || '',
    secret: current?.secret || '',
    extra: {
      ...(channel.extra || {}),
      ...(current?.extra || {}),
    },
  };
}

function formatMemoryLabel(key: string) {
  return key
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export default function SettingsPage() {
  const [section, setSection] = useState<(typeof SECTIONS)[number]>('General');
  const [config, setConfig] = useState<Record<string, any>>({});
  const [features, setFeatures] = useState<Record<string, FeatureEntry>>({});
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [backend, setBackend] = useState<{ running: boolean; port: number; healthy: boolean } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [restartRequired, setRestartRequired] = useState(false);

  const [selProvider, setSelProvider] = useState<ProviderId>('local');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [providerModels, setProviderModels] = useState<ModelOption[]>([]);
  const [providerModelsLoading, setProviderModelsLoading] = useState(false);
  const [localModelHealth, setLocalModelHealth] = useState<ModelHealthSnapshot | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  const [channels, setChannels] = useState<ChannelSnapshot[]>([]);
  const [channelDrafts, setChannelDrafts] = useState<Record<string, ChannelDraft>>({});
  const [channelSaving, setChannelSaving] = useState<Record<string, boolean>>({});
  const [channelTesting, setChannelTesting] = useState<Record<string, boolean>>({});
  const [channelPairing, setChannelPairing] = useState<Record<string, boolean>>({});
  const [channelResults, setChannelResults] = useState<Record<string, { ok: boolean; text: string } | null>>({});
  const [channelPairPayloads, setChannelPairPayloads] = useState<Record<string, PairPayload | null>>({});

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

  const selectedProviderMeta = useMemo(
    () => ALL_PROVIDERS.find((provider) => provider.id === selProvider) || ALL_PROVIDERS[ALL_PROVIDERS.length - 1],
    [selProvider],
  );

  const displayedModels = useMemo(() => {
    if (providerModels.length > 0) return providerModels;
    return DEFAULT_MODELS[selProvider] || [];
  }, [providerModels, selProvider]);

  const syncProviderState = (parsed: Record<string, any>) => {
    const providers = parsed.providers || {};
    const primary = String(providers.primary || 'local') as ProviderId;
    const providerId = ALL_PROVIDERS.some((provider) => provider.id === primary) ? primary : 'local';
    setSelProvider(providerId);
    setBaseUrl(String(providers?.[providerId]?.base_url || ''));
  };

  const refreshBackendStatus = async () => {
    try {
      const status = await invoke<{ running: boolean; port: number; healthy: boolean }>('get_backend_status');
      setBackend(status);
    } catch {
      setBackend(null);
    }
  };

  const refreshConfig = async () => {
    try {
      const parsed = await getConfig();
      setConfig(parsed);
      syncProviderState(parsed);
      setRestartRequired(false);
    } catch {
      setConfig({});
    }
  };

  const refreshFeatures = async () => {
    try {
      const next = await getFeatures();
      setFeatures(next);
    } catch {
      setFeatures({});
    }
  };

  const refreshMemoryStats = async () => {
    try {
      const stats = await getMemoryStats();
      setMemoryStats(stats);
    } catch {
      setMemoryStats(null);
    }
  };

  const refreshChannels = async () => {
    try {
      const snapshots = await getChannels();
      setChannels(snapshots);
      setChannelDrafts((current) => {
        const next: Record<string, ChannelDraft> = {};
        snapshots.forEach((channel) => {
          next[channel.name] = normalizeDraft(channel, current[channel.name]);
        });
        return next;
      });
    } catch {
      setChannels([]);
    }
  };

  const refreshLocalModelHealth = async () => {
    try {
      const snapshot = await getLocalModelHealth();
      setLocalModelHealth(snapshot);
    } catch {
      setLocalModelHealth(null);
    }
  };

  useEffect(() => {
    void hydrateAvatar();
    void Promise.all([
      refreshConfig(),
      refreshFeatures(),
      refreshMemoryStats(),
      refreshChannels(),
      refreshLocalModelHealth(),
      refreshBackendStatus(),
    ]);
  }, [hydrateAvatar]);

  useEffect(() => {
    let cancelled = false;
    const loadModels = async () => {
      setProviderModelsLoading(true);
      try {
        const models = await getProviderModels(selProvider, baseUrl || undefined, apiKey || undefined);
        if (!cancelled) setProviderModels(models);
      } catch {
        if (!cancelled) setProviderModels([]);
      } finally {
        if (!cancelled) setProviderModelsLoading(false);
      }
    };
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, [apiKey, baseUrl, selProvider]);

  const save = async (updates: Record<string, unknown>) => {
    setSaving(true);
    setMsg(null);
    try {
      const result = await updateDashboardConfig(updates);
      if (!result.ok) {
        setMsg({ ok: false, text: result.error || 'Failed to save settings.' });
        return;
      }
      if (result.config) {
        setConfig(result.config);
        syncProviderState(result.config);
      }
      if (result.restart_required) {
        setRestartRequired(true);
      }
      setMsg({
        ok: true,
        text: result.restart_required ? 'Saved. Restart the backend to apply all changes.' : 'Saved.',
      });
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to save settings.' });
    } finally {
      setSaving(false);
    }
  };

  const saveSectionPatch = (sectionName: string, patch: Record<string, unknown>) => {
    const currentSection = (config[sectionName] as Record<string, unknown> | undefined) || {};
    void save({ [sectionName]: { ...currentSection, ...patch } });
  };

  const restartBackendNow = async () => {
    setMsg(null);
    try {
      try {
        await invoke('stop_backend');
      } catch {
        // Backend may already be stopped.
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      await invoke('start_backend');
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
      await Promise.all([refreshBackendStatus(), refreshFeatures(), refreshMemoryStats(), refreshChannels(), refreshConfig()]);
      setRestartRequired(false);
      setMsg({ ok: true, text: 'Backend restarted.' });
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to restart backend.' });
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const raw = await invoke<string>('validate_api_key', {
        provider: selProvider,
        apiKey: apiKey || 'test',
        endpoint: baseUrl || undefined,
      });
      const parsed = JSON.parse(raw) as { valid?: boolean };
      setTestResult(parsed.valid
        ? { ok: true, text: 'Provider connection looks healthy.' }
        : { ok: false, text: 'Provider test failed. Check API key, URL, or local runtime.' });
    } catch (error: any) {
      setTestResult({ ok: false, text: error?.message || 'Provider test failed.' });
    } finally {
      setTesting(false);
    }
  };

  const saveProvider = async () => {
    const existingProviderConfig = config.providers?.[selProvider] || {};
    await save({
      providers: {
        ...(config.providers || {}),
        primary: selProvider,
        [selProvider]: {
          ...existingProviderConfig,
          base_url: baseUrl,
        },
      },
      provider_secrets: apiKey.trim() ? { [selProvider]: apiKey.trim() } : {},
    });
    setApiKey('');
  };

  const updateChannelDraft = (channelName: string, updater: (draft: ChannelDraft) => ChannelDraft) => {
    setChannelDrafts((current) => {
      const existing = current[channelName] || {
        enabled: false,
        trust_mode: '',
        secret: '',
        extra: {},
      };
      return {
        ...current,
        [channelName]: updater(existing),
      };
    });
  };

  const saveChannelConfig = async (channelName: string) => {
    const draft = channelDrafts[channelName];
    if (!draft) return;
    setChannelSaving((current) => ({ ...current, [channelName]: true }));
    setChannelResults((current) => ({ ...current, [channelName]: null }));
    try {
      const result = await updateChannel(channelName, draft);
      if (!result.ok) {
        setChannelResults((current) => ({
          ...current,
          [channelName]: { ok: false, text: result.error || 'Failed to save channel.' },
        }));
        return;
      }
      setRestartRequired(true);
      setChannelResults((current) => ({
        ...current,
        [channelName]: { ok: true, text: 'Saved. Restart the backend to apply channel changes.' },
      }));
      await refreshChannels();
    } catch (error: any) {
      setChannelResults((current) => ({
        ...current,
        [channelName]: { ok: false, text: error?.message || 'Failed to save channel.' },
      }));
    } finally {
      setChannelSaving((current) => ({ ...current, [channelName]: false }));
    }
  };

  const testChannelConfig = async (channelName: string) => {
    const draft = channelDrafts[channelName];
    if (!draft) return;
    setChannelTesting((current) => ({ ...current, [channelName]: true }));
    setChannelResults((current) => ({ ...current, [channelName]: null }));
    try {
      const result = await testChannel(channelName, draft);
      setChannelResults((current) => ({
        ...current,
        [channelName]: {
          ok: result.ok,
          text: result.ok ? (result.message || 'Channel test succeeded.') : (result.error || 'Channel test failed.'),
        },
      }));
    } catch (error: any) {
      setChannelResults((current) => ({
        ...current,
        [channelName]: { ok: false, text: error?.message || 'Channel test failed.' },
      }));
    } finally {
      setChannelTesting((current) => ({ ...current, [channelName]: false }));
    }
  };

  const pairChannelConfig = async (channelName: string) => {
    const draft = channelDrafts[channelName];
    if (!draft) return;
    setChannelPairing((current) => ({ ...current, [channelName]: true }));
    setChannelResults((current) => ({ ...current, [channelName]: null }));
    setChannelPairPayloads((current) => ({ ...current, [channelName]: null }));
    try {
      const result = await pairChannel(channelName, draft);
      setChannelResults((current) => ({
        ...current,
        [channelName]: {
          ok: result.ok,
          text: result.ok
            ? (result.message || (result.paired ? 'Already paired.' : 'QR generated. Scan it on your phone.'))
            : (result.error || 'Pairing failed.'),
        },
      }));
      if (result.ok) {
        setChannelPairPayloads((current) => ({
          ...current,
          [channelName]: {
            authDir: result.auth_dir,
            qrData: result.qr_data,
            qrDataUrl: result.qr_data_url,
            paired: result.paired,
          },
        }));
        if (result.auth_dir) {
          updateChannelDraft(channelName, (existing) => ({
            ...existing,
            secret: result.auth_dir || existing.secret,
            extra: { ...existing.extra, auth_dir: result.auth_dir },
          }));
        }
      }
    } catch (error: any) {
      setChannelResults((current) => ({
        ...current,
        [channelName]: { ok: false, text: error?.message || 'Pairing failed.' },
      }));
    } finally {
      setChannelPairing((current) => ({ ...current, [channelName]: false }));
    }
  };

  const toggleFeatureValue = async (key: string, value: boolean, live: boolean) => {
    setMsg(null);
    try {
      const result = await setFeature(key, value);
      if (!result.ok) {
        setMsg({ ok: false, text: 'Failed to update feature flag.' });
        return;
      }
      setFeatures((current) => ({
        ...current,
        [key]: { ...current[key], value },
      }));
      if (!live) setRestartRequired(true);
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to update feature flag.' });
    }
  };

  const providerCardGrid = (
    <div className="provider-grid" style={{ marginBottom: 18 }}>
      {ALL_PROVIDERS.map((provider) => {
        const colors = PROVIDER_COLORS[provider.id];
        const selected = selProvider === provider.id;
        return (
          <button
            key={provider.id}
            type="button"
            className={`provider-card ${selected ? 'selected' : ''}`}
            onClick={() => {
              setSelProvider(provider.id);
              setApiKey('');
              setTestResult(null);
              setBaseUrl(String(config.providers?.[provider.id]?.base_url || ''));
            }}
          >
            {selected && <div className="check-badge">✓</div>}
            <div className="provider-icon" style={{ background: colors.bg, color: colors.text }}>
              {colors.icon}
            </div>
            <div className="provider-name">{provider.name}</div>
            <div className="provider-company">{provider.company}</div>
          </button>
        );
      })}
    </div>
  );

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
                marginBottom: 14,
                background: msg.ok ? 'var(--accent-green-muted)' : 'var(--accent-red-muted)',
                borderColor: msg.ok ? 'rgba(63, 185, 80, 0.3)' : 'rgba(248, 81, 73, 0.3)',
              }}
            >
              <span className="info-icon">{msg.ok ? '✓' : '!'}</span>
              <span>{msg.text}</span>
            </div>
          )}

          {restartRequired && (
            <div
              className="info-box"
              style={{
                marginBottom: 14,
                background: 'var(--accent-orange-muted)',
                borderColor: 'rgba(210, 153, 34, 0.28)',
              }}
            >
              <span className="info-icon">!</span>
              <span style={{ flex: 1 }}>Some settings are persisted but need a backend restart before they take full effect.</span>
              <button className="btn btn-secondary btn-sm" onClick={() => { void restartBackendNow(); }}>
                Restart Backend
              </button>
            </div>
          )}

          {section === 'General' && (
            <div className="settings-section">
              <h2>General</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Bot Name</div>
                  <div className="settings-row-desc">The name your assistant uses in the desktop app and channels.</div>
                </div>
                <input
                  className="input-field"
                  style={{ width: 250 }}
                  defaultValue={config.general?.name || 'NeuralClaw'}
                  onBlur={(event) => {
                    void save({ general: { ...(config.general || {}), name: event.target.value.trim() || 'NeuralClaw' } });
                  }}
                />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Log Level</div>
                  <div className="settings-row-desc">Backend logging verbosity for diagnostics and release testing.</div>
                </div>
                <select
                  className="input-field"
                  style={{ width: 140 }}
                  value={config.general?.log_level || 'INFO'}
                  onChange={(event) => {
                    void save({ general: { ...(config.general || {}), log_level: event.target.value } });
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
                  <div className="settings-row-desc">Installed desktop client version.</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>v{APP_VERSION}</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Backend Version</div>
                  <div className="settings-row-desc">Gateway engine version currently reported by the local sidecar.</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>{config.version || 'Unavailable'}</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Runtime</div>
                  <div className="settings-row-desc">Desktop framework stack.</div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>Tauri 2 + React 19</span>
              </div>
            </div>
          )}

          {section === 'Provider' && (
            <div className="settings-section">
              <h2>Provider</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Pick the primary model provider for NeuralClaw. Local providers also drive the chat-window model selector.
              </p>
              {providerCardGrid}

              <div className="card">
                <div className="card-header">
                  <span className="card-title">{selectedProviderMeta.name} Configuration</span>
                  {providerModelsLoading && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading models...</span>}
                </div>

                {!isLocalProvider(selProvider) && (
                  <div className="input-group" style={{ marginBottom: 14 }}>
                    <label className="input-label">API Key</label>
                    <input
                      className="input-field input-mono"
                      type="password"
                      placeholder="Paste your provider API key"
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                    />
                  </div>
                )}

                <div className="input-group" style={{ marginBottom: 14 }}>
                  <label className="input-label">Base URL</label>
                  <input
                    className="input-field input-mono"
                    placeholder={isLocalProvider(selProvider) ? 'http://localhost:11434/v1' : 'https://api.provider.com/v1'}
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                  />
                </div>

                <div className="input-hint" style={{ marginBottom: 16 }}>
                  {isLocalProvider(selProvider)
                    ? 'For Ollama-compatible local inference, keep the /v1 URL and make sure ollama serve is running.'
                    : 'Use a provider-compatible OpenAI-style endpoint when applicable.'}
                </div>

                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button className="btn btn-secondary" onClick={() => { void testConnection(); }} disabled={testing}>
                    {testing ? 'Testing...' : 'Test Connection'}
                  </button>
                  <button className="btn btn-primary" onClick={() => { void saveProvider(); }} disabled={saving}>
                    {saving ? 'Saving...' : 'Save Provider'}
                  </button>
                </div>

                {testResult && (
                  <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className={`status-dot ${testResult.ok ? 'online' : 'offline'}`} />
                    <span style={{ color: testResult.ok ? 'var(--accent-green)' : 'var(--accent-red)' }}>{testResult.text}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {section === 'Models' && (
            <div className="settings-section">
              <h2>Models</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Available models for the selected provider. Local models also appear in the main chat input so you can switch per session.
              </p>
              <div className="card">
                <div className="card-header">
                  <span className="card-title">{selectedProviderMeta.name} Models</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {providerModelsLoading ? 'Refreshing...' : `${displayedModels.length} visible`}
                  </span>
                </div>
                {displayedModels.length === 0 ? (
                  <div className="empty-state" style={{ padding: 24 }}>
                    <span className="empty-icon">M</span>
                    <h3>No Models Found</h3>
                    <p>Save the provider URL first, then refresh the settings page to load its model catalog.</p>
                  </div>
                ) : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {displayedModels.map((model) => (
                      <div
                        key={model.name}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 12,
                          padding: '10px 12px',
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-tertiary)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontWeight: 700 }}>{model.icon}</span>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>{model.name}</span>
                        </div>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{model.description}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {isLocalProvider(selProvider) && (
                <div className="card" style={{ marginTop: 16 }}>
                  <div className="card-header">
                    <span className="card-title">Local Model Health</span>
                    <button className="btn btn-secondary" onClick={() => { void refreshLocalModelHealth(); }}>
                      Refresh
                    </button>
                  </div>
                  {!localModelHealth ? (
                    <div className="empty-state" style={{ padding: 24 }}>
                      <span className="empty-icon">LH</span>
                      <h3>No Local Runtime Data</h3>
                      <p>NeuralClaw could not reach the configured Ollama endpoint for live health data.</p>
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gap: 10 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        Endpoint: {localModelHealth.resolved_base_url || 'unresolved'}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {localModelHealth.badges.map((badge) => (
                          <span key={`${badge.label}-${badge.model}`} className={`badge ${badge.available ? 'badge-green' : 'badge-red'}`}>
                            {badge.label}: {badge.model}
                          </span>
                        ))}
                      </div>
                      <div style={{ display: 'grid', gap: 8 }}>
                        {localModelHealth.models.map((model) => (
                          <div
                            key={model}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              gap: 12,
                              padding: '10px 12px',
                              borderRadius: 'var(--radius-sm)',
                              background: 'var(--bg-tertiary)',
                            }}
                          >
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>{model}</span>
                            <span className="badge badge-green">available</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {section === 'Channels' && (
            <div className="settings-section">
              <h2>Channels</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Configure Telegram, Discord, Slack, WhatsApp, and Signal from the desktop app.
              </p>
              {channels.length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">#</span>
                  <h3>No Channel Data</h3>
                  <p>Connect to the backend to manage external communication channels.</p>
                </div>
              ) : (
                channels.map((channel) => {
                  const draft = channelDrafts[channel.name] || normalizeDraft(channel);
                  const meta = CHANNEL_META[channel.name];
                  const result = channelResults[channel.name];
                  const pairPayload = channelPairPayloads[channel.name];
                  return (
                    <div key={channel.name} className="card" style={{ marginBottom: 16 }}>
                      <div className="card-header">
                        <div>
                          <span className="card-title">{channel.label}</span>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>{channel.description}</div>
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <span className={`badge ${channel.configured ? 'badge-orange' : 'badge-red'}`}>
                            {channel.configured ? 'Configured' : 'Not Configured'}
                          </span>
                          <span className={`badge ${channel.running ? 'badge-green' : 'badge-blue'}`}>
                            {channel.running ? 'Running' : 'Saved'}
                          </span>
                        </div>
                      </div>

                      <div className="settings-row">
                        <div>
                          <div className="settings-row-label">Enabled</div>
                          <div className="settings-row-desc">Register this channel when the backend starts.</div>
                        </div>
                        <button
                          className={`toggle ${draft.enabled ? 'on' : ''}`}
                          onClick={() => {
                            updateChannelDraft(channel.name, (current) => ({ ...current, enabled: !current.enabled }));
                          }}
                        />
                      </div>

                      <div className="settings-row">
                        <div>
                          <div className="settings-row-label">Trust Mode</div>
                          <div className="settings-row-desc">How unknown senders are treated on this channel.</div>
                        </div>
                        <select
                          className="input-field"
                          style={{ width: 220 }}
                          value={draft.trust_mode}
                          onChange={(event) => {
                            const value = event.target.value;
                            updateChannelDraft(channel.name, (current) => ({ ...current, trust_mode: value }));
                          }}
                        >
                          {TRUST_MODES.map((mode) => (
                            <option key={mode.label} value={mode.value}>
                              {mode.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="settings-row">
                        <div>
                          <div className="settings-row-label">{meta.secretLabel}</div>
                          <div className="settings-row-desc">{meta.hint}</div>
                        </div>
                        <div style={{ width: 400 }}>
                          <input
                            className="input-field input-mono"
                            type={channel.name === 'whatsapp' ? 'text' : 'password'}
                            value={String(channel.name === 'whatsapp' ? (draft.extra.auth_dir || draft.secret || '') : draft.secret)}
                            placeholder={meta.placeholder}
                            onChange={(event) => {
                              const value = event.target.value;
                              updateChannelDraft(channel.name, (current) => ({
                                ...current,
                                secret: channel.name === 'whatsapp' ? value : value,
                                extra: channel.name === 'whatsapp'
                                  ? { ...current.extra, auth_dir: value }
                                  : current.extra,
                              }));
                            }}
                          />
                        </div>
                      </div>

                      {channel.name === 'slack' && (
                        <div className="settings-row">
                          <div>
                            <div className="settings-row-label">App Token</div>
                            <div className="settings-row-desc">Slack app-level token for Socket Mode.</div>
                          </div>
                          <div style={{ width: 400 }}>
                            <input
                              className="input-field input-mono"
                              type="password"
                              value={String(draft.extra.slack_app || '')}
                              placeholder="xapp-..."
                              onChange={(event) => {
                                const value = event.target.value;
                                updateChannelDraft(channel.name, (current) => ({
                                  ...current,
                                  extra: { ...current.extra, slack_app: value },
                                }));
                              }}
                            />
                          </div>
                        </div>
                      )}

                      {channel.name === 'discord' && (
                        <>
                          <div className="settings-row">
                            <div>
                              <div className="settings-row-label">Voice Responses</div>
                              <div className="settings-row-desc">Allow Discord voice output when a voice session is active.</div>
                            </div>
                            <button
                              className={`toggle ${Boolean(draft.extra.voice_responses) ? 'on' : ''}`}
                              onClick={() => {
                                updateChannelDraft(channel.name, (current) => ({
                                  ...current,
                                  extra: { ...current.extra, voice_responses: !Boolean(current.extra.voice_responses) },
                                }));
                              }}
                            />
                          </div>
                          <div className="settings-row">
                            <div>
                              <div className="settings-row-label">Voice Channel ID</div>
                              <div className="settings-row-desc">Optional fixed voice channel for automated joins.</div>
                            </div>
                            <input
                              className="input-field input-mono"
                              style={{ width: 220 }}
                              value={String(draft.extra.voice_channel_id || '')}
                              onChange={(event) => {
                                const value = event.target.value;
                                updateChannelDraft(channel.name, (current) => ({
                                  ...current,
                                  extra: { ...current.extra, voice_channel_id: value },
                                }));
                              }}
                            />
                          </div>
                        </>
                      )}

                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 16 }}>
                        <button
                          className="btn btn-secondary"
                          onClick={() => { void testChannelConfig(channel.name); }}
                          disabled={Boolean(channelTesting[channel.name])}
                        >
                          {channelTesting[channel.name] ? 'Testing...' : 'Test'}
                        </button>
                        {channel.name === 'whatsapp' && (
                          <button
                            className="btn btn-secondary"
                            onClick={() => { void pairChannelConfig(channel.name); }}
                            disabled={Boolean(channelPairing[channel.name])}
                          >
                            {channelPairing[channel.name] ? 'Generating QR...' : 'Pair QR'}
                          </button>
                        )}
                        <button
                          className="btn btn-primary"
                          onClick={() => { void saveChannelConfig(channel.name); }}
                          disabled={Boolean(channelSaving[channel.name])}
                        >
                          {channelSaving[channel.name] ? 'Saving...' : 'Save Channel'}
                        </button>
                      </div>

                      {result && (
                        <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span className={`status-dot ${result.ok ? 'online' : 'offline'}`} />
                          <span style={{ color: result.ok ? 'var(--accent-green)' : 'var(--accent-red)', fontSize: 13 }}>
                            {result.text}
                          </span>
                        </div>
                      )}

                      {channel.name === 'whatsapp' && pairPayload && (
                        <div className="card" style={{ marginTop: 14, padding: 16 }}>
                          <div className="card-title" style={{ marginBottom: 8 }}>WhatsApp Pairing</div>
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                            {pairPayload.paired
                              ? 'This auth directory is already paired. Save the channel, then restart the backend.'
                              : 'Scan the QR code inside WhatsApp > Linked Devices > Link a Device, then save the channel and restart the backend.'}
                          </div>
                          {pairPayload.authDir && (
                            <div style={{ marginBottom: 12, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
                              {pairPayload.authDir}
                            </div>
                          )}
                          {pairPayload.qrDataUrl ? (
                            <img
                              src={pairPayload.qrDataUrl}
                              alt="WhatsApp pairing QR"
                              style={{ width: 220, height: 220, borderRadius: 16, background: '#fff', padding: 12 }}
                            />
                          ) : pairPayload.qrData ? (
                            <pre
                              style={{
                                margin: 0,
                                padding: 12,
                                background: 'var(--bg-input)',
                                borderRadius: 'var(--radius-sm)',
                                whiteSpace: 'pre-wrap',
                                overflowX: 'auto',
                              }}
                            >
                              {pairPayload.qrData}
                            </pre>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          )}

          {section === 'Memory' && (
            <div className="settings-section">
              <h2>Memory</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Inspect live memory counts and confirm the desktop feature toggles are actually controlling the backend subsystems.
              </p>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-header">
                  <span className="card-title">Live Memory Counts</span>
                  <button className="btn btn-secondary btn-sm" onClick={() => { void refreshMemoryStats(); }}>
                    Refresh
                  </button>
                </div>
                <div className="stats-grid">
                  <div className="stat-card">
                    <div className="stat-label">Episodic</div>
                    <div className="stat-value">{memoryStats?.episodic_count ?? '-'}</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Semantic</div>
                    <div className="stat-value">{memoryStats?.semantic_count ?? '-'}</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Procedural</div>
                    <div className="stat-value">{memoryStats?.procedural_count ?? '-'}</div>
                  </div>
                </div>
              </div>

              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-header">
                  <span className="card-title">Memory Feature Flags</span>
                </div>
                {Object.entries(features)
                  .filter(([key]) => ['semantic_memory', 'procedural_memory', 'evolution_cortex'].includes(key))
                  .map(([key, feature]) => (
                    <div key={key} className="settings-row">
                      <div>
                        <div className="settings-row-label">{feature.label || formatMemoryLabel(key)}</div>
                        <div className="settings-row-desc">
                          {feature.live ? 'Live change.' : 'Requires backend restart after saving.'}
                        </div>
                      </div>
                      <button
                        className={`toggle ${feature.value ? 'on' : ''}`}
                        onClick={() => { void toggleFeatureValue(key, !feature.value, feature.live); }}
                      />
                    </div>
                  ))}
              </div>

              <button
                className="btn btn-danger"
                onClick={() => {
                  if (!window.confirm('Clear all episodic, semantic, and procedural memory? This cannot be undone.')) return;
                  void (async () => {
                    try {
                      await clearMemory();
                      await refreshMemoryStats();
                      setMsg({ ok: true, text: 'Cleared all backend memory stores.' });
                    } catch (error: any) {
                      setMsg({ ok: false, text: error?.message || 'Failed to clear memory.' });
                    }
                  })();
                }}
              >
                Clear All Memory
              </button>
            </div>
          )}

          {section === 'Avatar' && (
            <div className="settings-section">
              <h2>Avatar</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Configure the floating companion window, sizing, anchor placement, and custom VRM model.
              </p>
              <div className="card">
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Avatar Mode</div>
                    <div className="settings-row-desc">Show or hide the floating avatar window.</div>
                  </div>
                  <button className={`toggle ${avatarVisible ? 'on' : ''}`} onClick={() => { void toggleVisible(); }} />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Anchor Position</div>
                    <div className="settings-row-desc">Snap to a corner, the taskbar, or leave it freely positioned.</div>
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
                    <div className="settings-row-desc">Resize the avatar from 0.5x to 2.0x.</div>
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
                    <div className="settings-row-desc">Upload a .vrm avatar file or keep the built-in assistant.</div>
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
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 280 }}>
                      {avatarModelPath || 'Built-in NeuralClaw avatar'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {section === 'Features' && (
            <div className="settings-section">
              <h2>Feature Flags</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Live features switch instantly. Everything else persists immediately and applies on the next backend restart.
              </p>
              {Object.keys(features).length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">F</span>
                  <h3>No Feature Data</h3>
                  <p>Connect to the backend to manage feature flags.</p>
                </div>
              ) : (
                Object.entries(features).map(([key, feature]) => (
                  <div key={key} className="settings-row">
                    <div>
                      <div className="settings-row-label">{feature.label || formatMemoryLabel(key)}</div>
                      <div className="settings-row-desc">
                        {feature.live ? 'Live toggle.' : 'Requires backend restart.'}
                      </div>
                    </div>
                    <button
                      className={`toggle ${feature.value ? 'on' : ''}`}
                      onClick={() => { void toggleFeatureValue(key, !feature.value, feature.live); }}
                    />
                  </div>
                ))
              )}
            </div>
          )}

          {section === 'Advanced' && (
            <div className="settings-section">
              <h2>Advanced</h2>

              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 14 }}>Backend Runtime</div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Backend Sidecar</div>
                    <div className="settings-row-desc">
                      {backend?.running
                        ? `Running on port ${backend.port}${backend.healthy ? ' and healthy.' : ', health check pending.'}`
                        : 'Stopped'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-primary btn-sm" onClick={() => { void invoke('start_backend').then(refreshBackendStatus); }}>
                      Start
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => { void restartBackendNow(); }}>
                      Restart
                    </button>
                    <button className="btn btn-danger btn-sm" onClick={() => { void invoke('stop_backend').then(refreshBackendStatus); }}>
                      Stop
                    </button>
                  </div>
                </div>
              </div>

              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 14 }}>Computer Use</div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Desktop Control</div>
                    <div className="settings-row-desc">Allow screenshots, clicks, typing, clipboard, and app launch tools.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(config.desktop?.enabled) ? 'on' : ''}`}
                    onClick={() => { saveSectionPatch('desktop', { enabled: !Boolean(config.desktop?.enabled) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Browser Automation</div>
                    <div className="settings-row-desc">Allow local browser control for task execution and QA.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(config.browser?.enabled) ? 'on' : ''}`}
                    onClick={() => { saveSectionPatch('browser', { enabled: !Boolean(config.browser?.enabled) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Shell Execution</div>
                    <div className="settings-row-desc">Allow the agent to run local commands for configuration, installs, and debugging.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(config.security?.allow_shell_execution) ? 'on' : ''}`}
                    onClick={() => { saveSectionPatch('security', { allow_shell_execution: !Boolean(config.security?.allow_shell_execution) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Action Delay (ms)</div>
                    <div className="settings-row-desc">Small pause between desktop actions for stability.</div>
                  </div>
                  <input
                    className="input-field input-mono"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    step={50}
                    defaultValue={Number(config.desktop?.action_delay_ms ?? 100)}
                    onBlur={(event) => {
                      const next = Number(event.target.value || 0);
                      saveSectionPatch('desktop', { action_delay_ms: Number.isFinite(next) ? Math.max(0, next) : 100 });
                    }}
                  />
                </div>
              </div>

              <div className="card">
                <div className="card-title" style={{ marginBottom: 14 }}>Local Reset Tools</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      if (!window.confirm('Delete all locally persisted desktop chat sessions?')) return;
                      void resetAllDesktopChatSessions().then(() => {
                        setMsg({ ok: true, text: 'Local desktop chats were reset.' });
                      }).catch((error: any) => {
                        setMsg({ ok: false, text: error?.message || 'Failed to reset local chats.' });
                      });
                    }}
                  >
                    Reset Local Chats
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={() => {
                      if (!window.confirm('Clear desktop cache and reload the app?')) return;
                      void resetAllDesktopChatSessions().finally(() => {
                        localStorage.clear();
                        window.location.reload();
                      });
                    }}
                  >
                    Reset Desktop Cache
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
