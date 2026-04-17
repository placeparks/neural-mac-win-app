import { useEffect, useMemo, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { ALL_PROVIDERS, DEFAULT_MODELS, PROVIDER_COLORS, type ProviderId } from '../lib/theme';
import { APP_VERSION } from '../lib/constants';
import { AUTONOMY_PROFILES, getAutonomyProfileById } from '../lib/autonomy';
import { filterChatCapableModels } from '../lib/models';
import { clearPersistedStore, deletePersistedValue } from '../lib/persistence';
import { invalidateVoiceAssistantCache } from '../lib/voiceAssistant';
import { useAvatarState } from '../avatar/useAvatarState';
import {
  captureAssistantScreen,
  clearMemory,
  exportMemoryBackup,
  getDesktopIntegrations,
  getChannels,
  getConfig,
  getFeatures,
  getSkills,
  getLocalModelHealth,
  getMemoryStats,
  getProviderModels,
  importMemoryBackup,
  pairChannel,
  resetChannel,
  resetAllDesktopChatSessions,
  runMemoryRetention,
  setFeature,
  testChannel,
  updateChannel,
  updateDashboardConfig,
  type ChannelSnapshot,
  type DesktopIntegration,
  type MemoryStats,
  type ModelHealthSnapshot,
  type ModelOption,
  type RuntimeSkillInfo,
} from '../lib/api';

const SECTIONS = ['General', 'Provider', 'Channels', 'Models', 'Memory', 'Assistant', 'Features', 'Advanced'] as const;

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
  pairingCode?: string;
  paired?: boolean;
}

interface PersistChannelOptions {
  successText?: string;
  silentResult?: boolean;
}

type AssistantCapability = 'desktop' | 'browser' | 'voice';

const SELF_CONFIG_TOOLS = [
  'list_features',
  'set_feature',
  'list_skills',
  'set_skill_enabled',
  'get_config',
  'list_available_models',
  'set_model_role',
] as const;

const FORGE_TOOLS = ['forge_skill', 'scout_skill'] as const;

const FEATURE_GROUPS: Array<{ title: string; keys: string[] }> = [
  { title: 'Core Intelligence', keys: ['reflective_reasoning', 'structured_output', 'streaming_responses', 'offline_fallback', 'traceline'] },
  { title: 'Memory + Knowledge', keys: ['vector_memory', 'identity', 'procedural_memory', 'semantic_memory', 'rag', 'workflow_engine'] },
  { title: 'Agents + Autonomy', keys: ['swarm', 'evolution', 'skill_forge', 'context_aware', 'digest', 'scheduler', 'kpi_monitor'] },
  { title: 'Computer + Integration Surfaces', keys: ['vision', 'voice', 'browser', 'desktop', 'database_bi', 'clipboard_intel', 'a2a_federation', 'mcp_server', 'dashboard'] },
] as const;

function isLocalProvider(provider: string) {
  return provider === 'local' || provider === 'meta';
}

function resolveConfiguredProviderId(parsed: Record<string, any>): ProviderId {
  const providers = parsed.providers || {};
  const requested = String(providers.primary || '').trim().toLowerCase();
  const normalized = requested === 'meta' ? 'local' : requested;
  return ALL_PROVIDERS.some((provider) => provider.id === normalized)
    ? normalized as ProviderId
    : 'local';
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

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

function resolveLocalBaseUrl(config: Record<string, unknown>) {
  const rolesCfg = asRecord(config.model_roles);
  const providersCfg = asRecord(config.providers);
  const localProviderCfg = asRecord(providersCfg.local);
  return String(rolesCfg.base_url || localProviderCfg.base_url || 'http://localhost:11434/v1');
}

// ---------------------------------------------------------------------------
// EmbedModelPicker - dedicated embedding model selector for Memory section
// ---------------------------------------------------------------------------
function EmbedModelPicker({
  config,
  saveSectionPatch,
}: {
  config: Record<string, unknown>;
  saveSectionPatch: (section: string, patch: Record<string, unknown>) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const memCfg = asRecord(config.memory);
  const rolesCfg = asRecord(config.model_roles);
  const currentEmbedModel =
    String(rolesCfg.embed || memCfg.embedding_model || '');
  const baseUrl = resolveLocalBaseUrl(config);

  const fetchModels = () => {
    setLoading(true);
    setError(null);
    getProviderModels('local', baseUrl)
      .then((list) => {
        setModels(list.map((m) => m.name));
        if (list.length === 0) setError('No models found at ' + baseUrl);
      })
      .catch(() => setError('Could not reach Ollama at ' + baseUrl))
      .finally(() => setLoading(false));
  };

  // Fetch on mount
  useEffect(() => { fetchModels(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (model: string) => {
    // Persist in both memory.embedding_model and model_roles.embed so
    // both code paths (role_router and direct vector.py) pick it up.
    saveSectionPatch('memory', { embedding_model: model });
    saveSectionPatch('model_roles', { embed: model });
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header">
        <span className="card-title">Embedding Model</span>
        <button
          className="btn btn-secondary btn-sm"
          onClick={fetchModels}
          disabled={loading}
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>
      <div style={{ padding: '12px 16px' }}>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
          Dedicated model used for vector memory, RAG, and semantic search.
          Embedding-only models belong here rather than in primary / fast / micro chat roles.
          Requires a restart to apply.
        </p>
        {error && (
          <p style={{ fontSize: 12, color: '#f87171', marginBottom: 10 }}>Warning: {error}</p>
        )}
        <div className="settings-row">
          <div>
            <div className="settings-row-label">Embed model</div>
            <div className="settings-row-desc">
              {currentEmbedModel
                ? `Currently: ${currentEmbedModel}`
                : 'Auto-detected at startup'}
            </div>
          </div>
          <select
            className="input-field"
            style={{ width: 220 }}
            value={currentEmbedModel}
            onChange={(e) => handleChange(e.target.value)}
            disabled={loading || models.length === 0}
          >
            <option value="">Auto-detect</option>
            {models.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

function SearchProvidersSettings({
  config,
  onSave,
}: {
  config: Record<string, unknown>;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const apiConfig = asRecord(config.apis);
  const googleSearch = asRecord(apiConfig.google_search);
  const searxng = asRecord(apiConfig.searxng);
  const [tavilyKey, setTavilyKey] = useState('');
  const [braveKey, setBraveKey] = useState('');
  const [serperKey, setSerperKey] = useState('');
  const [googleKey, setGoogleKey] = useState('');
  const [googleCx, setGoogleCx] = useState(String(googleSearch.cx || ''));
  const [searxngUrl, setSearxngUrl] = useState(String(searxng.base_url || ''));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setGoogleCx(String(asRecord(asRecord(config.apis).google_search).cx || ''));
    setSearxngUrl(String(asRecord(asRecord(config.apis).searxng).base_url || ''));
    setMessage(null);
  }, [config]);

  const saveProviders = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const apis = asRecord(config.apis);
      const providerSecrets: Record<string, string> = {};
      if (tavilyKey.trim()) providerSecrets.tavily = tavilyKey.trim();
      if (braveKey.trim()) providerSecrets.brave = braveKey.trim();
      if (serperKey.trim()) providerSecrets.serper = serperKey.trim();
      if (googleKey.trim()) providerSecrets.google_search = googleKey.trim();

      await onSave({
        apis: {
          ...apis,
          google_search: {
            ...asRecord(apis.google_search),
            cx: googleCx.trim(),
          },
          searxng: {
            ...asRecord(apis.searxng),
            base_url: searxngUrl.trim(),
          },
        },
        ...(Object.keys(providerSecrets).length > 0 ? { provider_secrets: providerSecrets } : {}),
      });

      setTavilyKey('');
      setBraveKey('');
      setSerperKey('');
      setGoogleKey('');
      setMessage('Search providers saved. Tavily > Brave > Serper > Google > SearXNG > DuckDuckGo will apply automatically.');
    } finally {
      setBusy(false);
    }
  };

  const providerRows: Array<{ label: string; hint: string; value: string; setValue: (value: string) => void; placeholder: string }> = [
    {
      label: 'Tavily API Key',
      hint: 'Highest-quality research provider for agent answers and recommendation queries.',
      value: tavilyKey,
      setValue: setTavilyKey,
      placeholder: 'tvly-...',
    },
    {
      label: 'Brave Search API Key',
      hint: 'Strong general-purpose web search fallback with good freshness.',
      value: braveKey,
      setValue: setBraveKey,
      placeholder: 'brave-search-key',
    },
    {
      label: 'Serper API Key',
      hint: 'Google-result API with fast structured search responses.',
      value: serperKey,
      setValue: setSerperKey,
      placeholder: 'serper-key',
    },
    {
      label: 'Google Custom Search API Key',
      hint: 'Pairs with the Search Engine ID below for Google Custom Search JSON API.',
      value: googleKey,
      setValue: setGoogleKey,
      placeholder: 'google-search-key',
    },
  ];

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-title" style={{ marginBottom: 14 }}>Web Research Providers</div>
      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
        Configure the providers the agent should use for recommendation and research questions. Leave any secret blank to keep the existing stored value.
      </p>
      <div style={{ display: 'grid', gap: 12 }}>
        {providerRows.map((row) => (
          <div key={row.label} className="settings-row">
            <div>
              <div className="settings-row-label">{row.label}</div>
              <div className="settings-row-desc">{row.hint}</div>
            </div>
            <input
              className="input-field"
              style={{ width: 320 }}
              type="password"
              placeholder={row.placeholder}
              value={row.value}
              onChange={(event) => row.setValue(event.target.value)}
            />
          </div>
        ))}
        <div className="settings-row">
          <div>
            <div className="settings-row-label">Google Search Engine ID</div>
            <div className="settings-row-desc">Required for Google Custom Search. Saved in config under `apis.google_search.cx`.</div>
          </div>
          <input
            className="input-field input-mono"
            style={{ width: 320 }}
            placeholder="custom search engine id"
            value={googleCx}
            onChange={(event) => setGoogleCx(event.target.value)}
          />
        </div>
        <div className="settings-row">
          <div>
            <div className="settings-row-label">SearXNG Base URL</div>
            <div className="settings-row-desc">Optional self-hosted search endpoint. Example: `https://search.example.com`.</div>
          </div>
          <input
            className="input-field input-mono"
            style={{ width: 320 }}
            placeholder="https://search.example.com"
            value={searxngUrl}
            onChange={(event) => setSearxngUrl(event.target.value)}
          />
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Current runtime order: Tavily, Brave, Serper, Google Custom Search, SearXNG, then DuckDuckGo fallback.
        </div>
        {message ? <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div> : null}
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={() => { void saveProviders(); }} disabled={busy}>
            {busy ? 'Saving...' : 'Save Search Providers'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ModelRolesPicker({
  config,
  saveSectionPatch,
}: {
  config: Record<string, unknown>;
  saveSectionPatch: (section: string, patch: Record<string, unknown>) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rolesCfg = asRecord(config.model_roles);
  const baseUrl = resolveLocalBaseUrl(config);
  const enabled = Boolean(rolesCfg.enabled);
  const currentPrimary = String(rolesCfg.primary || '');
  const currentFast = String(rolesCfg.fast || rolesCfg.primary || '');
  const currentMicro = String(rolesCfg.micro || rolesCfg.primary || '');

  const fetchModels = () => {
    setLoading(true);
    setError(null);
    getProviderModels('local', baseUrl)
      .then((list) => {
        const names = filterChatCapableModels(list).map((m) => m.name).filter(Boolean);
        setModels(names);
        if (names.length === 0) setError('No local models found at ' + baseUrl);
      })
      .catch(() => setError('Could not reach Ollama at ' + baseUrl))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchModels(); }, [baseUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateRole = (role: 'primary' | 'fast' | 'micro', model: string) => {
    const patch: Record<string, unknown> = { [role]: model };
    if (role === 'primary') {
      const existingFast = String(rolesCfg.fast || '');
      const existingMicro = String(rolesCfg.micro || '');
      if (!existingFast || existingFast === currentPrimary) patch.fast = model;
      if (!existingMicro || existingMicro === currentPrimary) patch.micro = model;
    }
    saveSectionPatch('model_roles', patch);
  };

  const roles: Array<{ key: 'primary' | 'fast' | 'micro'; label: string; value: string; hint: string }> = [
    { key: 'primary', label: 'Primary', value: currentPrimary, hint: 'Deep reasoning and final user-facing responses.' },
    { key: 'fast', label: 'Fast', value: currentFast, hint: 'Tool loops and intermediate passes.' },
    { key: 'micro', label: 'Micro', value: currentMicro, hint: 'Routing, classification, and short decisions.' },
  ];

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header">
        <span className="card-title">Model Roles</span>
        <button
          className="btn btn-secondary btn-sm"
          onClick={fetchModels}
          disabled={loading}
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>
      <div style={{ padding: '12px 16px', display: 'grid', gap: 12 }}>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 0 }}>
          Route heavy reasoning to a larger model and send `fast` / `micro` work to smaller models on the same Ollama endpoint.
        </p>
        <div className="settings-row">
          <div>
            <div className="settings-row-label">Enable role routing</div>
            <div className="settings-row-desc">
              When off, the role mappings stay saved but the runtime will not actively dispatch by `primary`, `fast`, or `micro`.
            </div>
          </div>
          <button
            className={`toggle ${enabled ? 'on' : ''}`}
            onClick={() => saveSectionPatch('model_roles', { enabled: !enabled })}
          />
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 0 }}>
          Embedding-only models are hidden here. Use the dedicated embedding picker below for vector memory and RAG.
        </p>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          Endpoint: {baseUrl}
        </div>
        {error && (
          <p style={{ fontSize: 12, color: '#f87171', marginBottom: 0 }}>Warning: {error}</p>
        )}
        {roles.map((role) => (
          <div key={role.key} className="settings-row">
            <div>
              <div className="settings-row-label">{role.label}</div>
              <div className="settings-row-desc">{role.hint}</div>
            </div>
            <select
              className="input-field"
              style={{ width: 240 }}
              value={role.value}
              onChange={(event) => updateRole(role.key, event.target.value)}
              disabled={loading || models.length === 0}
            >
              <option value="">Unassigned</option>
              {models.map((model) => (
                <option key={`${role.key}-${model}`} value={model}>{model}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </div>
  );
}

function IntegrationOverview({ integrations }: { integrations: DesktopIntegration[] }) {
  if (integrations.length === 0) {
    return (
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ padding: '16px 18px' }}>
          <div className="card-title" style={{ marginBottom: 8 }}>Integrations</div>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
            No integration inventory available from the backend yet.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header">
        <span className="card-title">Integrations</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{integrations.length} detected</span>
      </div>
      <div style={{ padding: '12px 16px', display: 'grid', gap: 10 }}>
        {integrations.map((integration) => (
          <div
            key={integration.id}
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 1fr) auto auto',
              gap: 12,
              alignItems: 'center',
              padding: '10px 12px',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-tertiary)',
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{integration.label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{integration.summary}</div>
            </div>
            <span className="badge">{integration.category}</span>
            <span className={`badge badge-${integration.connected ? 'green' : integration.enabled ? 'orange' : 'blue'}`}>
              {integration.connected ? 'connected' : integration.enabled ? 'configured' : 'idle'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [section, setSection] = useState<(typeof SECTIONS)[number]>('General');
  const [config, setConfig] = useState<Record<string, any>>({});
  const [features, setFeatures] = useState<Record<string, FeatureEntry>>({});
  const [runtimeSkills, setRuntimeSkills] = useState<RuntimeSkillInfo[]>([]);
  const [integrations, setIntegrations] = useState<DesktopIntegration[]>([]);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [backend, setBackend] = useState<{ running: boolean; port: number; healthy: boolean } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [restartRequired, setRestartRequired] = useState(false);

  const [selProvider, setSelProvider] = useState<ProviderId>('openai');
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
  const [channelResetting, setChannelResetting] = useState<Record<string, boolean>>({});
  const [channelResults, setChannelResults] = useState<Record<string, { ok: boolean; text: string } | null>>({});
  const [channelPairPayloads, setChannelPairPayloads] = useState<Record<string, PairPayload | null>>({});
  const [memoryBackupPassphrase, setMemoryBackupPassphrase] = useState('');
  const [memoryBackupPayload, setMemoryBackupPayload] = useState('');
  const [assistantScreenBusy, setAssistantScreenBusy] = useState(false);
  const [assistantScreen, setAssistantScreen] = useState<{ dataUrl: string; width: number; height: number; monitor: number } | null>(null);
  const [voicePreviewBusy, setVoicePreviewBusy] = useState(false);
  const [assistantSaving, setAssistantSaving] = useState<Record<AssistantCapability, boolean>>({
    desktop: false,
    browser: false,
    voice: false,
  });
  const [autonomySaving, setAutonomySaving] = useState(false);

  const {
    hydrate: hydrateAvatar,
    visible: avatarVisible,
    anchor: avatarAnchor,
    scale: avatarScale,
    modelPath: avatarModelPath,
    renderMode: avatarRenderMode,
    toggleVisible,
    setAnchor: setAvatarAnchor,
    setScale: setAvatarScale,
    setRenderMode: setAvatarRenderMode,
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

  const getWhatsAppAuthDir = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    const extra = asRecord(channel.extra);
    return String(
      draft.extra.auth_dir ||
      draft.secret ||
      extra.auth_dir ||
      extra.default_auth_dir ||
      '',
    ).trim();
  };

  const getChannelSecretValue = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    if (channel.name === 'whatsapp') return getWhatsAppAuthDir(channel, draft);
    return String(draft.secret || '').trim();
  };

  const getChannelExtraValue = (channel: ChannelSnapshot, draft: ChannelDraft, key: string) => {
    const extra = asRecord(channel.extra);
    return String(draft.extra[key] || extra[key] || '').trim();
  };

  const channelValidationErrorsForDraft = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    const errors: string[] = [];
    const secret = channel.name === 'whatsapp' ? '' : getChannelSecretValue(channel, draft);

    if (channel.name === 'telegram') {
      if (secret && !/^\d{6,12}:[A-Za-z0-9_-]{20,}$/.test(secret)) {
        errors.push('Telegram bot token format looks invalid.');
      }
      const chatId = getChannelExtraValue(channel, draft, 'default_chat_id');
      if (chatId && !(/^[-]?\d+$/.test(chatId) || /^@[A-Za-z][A-Za-z0-9_]{4,}$/.test(chatId))) {
        errors.push('Telegram default chat ID must be numeric or an @channelusername.');
      }
    }
    if (channel.name === 'discord') {
      for (const [key, label] of [['guild_id', 'Discord server ID'], ['text_channel_id', 'Discord text channel ID'], ['voice_channel_id', 'Discord voice channel ID']] as const) {
        const value = getChannelExtraValue(channel, draft, key);
        if (value && !/^\d{15,22}$/.test(value)) {
          errors.push(`${label} must be numeric.`);
          break;
        }
      }
      if (Boolean(draft.extra.voice_responses || asRecord(channel.extra).voice_responses) && !getChannelExtraValue(channel, draft, 'voice_channel_id')) {
        errors.push('Discord voice responses require a voice channel ID.');
      }
    }
    if (channel.name === 'slack') {
      const botToken = getChannelSecretValue(channel, draft);
      const appToken = getChannelExtraValue(channel, draft, 'slack_app');
      if (botToken && !botToken.startsWith('xoxb-')) errors.push('Slack bot token must start with xoxb-.');
      if (appToken && !appToken.startsWith('xapp-')) errors.push('Slack app token must start with xapp-.');
      const teamId = getChannelExtraValue(channel, draft, 'team_id');
      if (teamId && !/^T[A-Z0-9]+$/.test(teamId)) errors.push('Slack workspace ID must look like T0123456789.');
      const defaultChannelId = getChannelExtraValue(channel, draft, 'default_channel_id');
      if (defaultChannelId && !/^[CDG][A-Z0-9]+$/.test(defaultChannelId)) {
        errors.push('Slack default channel ID must look like C..., D..., or G....');
      }
    }
    if (channel.name === 'whatsapp') {
      const authDir = getWhatsAppAuthDir(channel, draft);
      if (authDir && authDir.length < 3) errors.push('WhatsApp auth directory path is too short.');
      const phoneNumber = getChannelExtraValue(channel, draft, 'phone_number');
      if (phoneNumber && !/^\d{7,15}$/.test(phoneNumber)) {
        errors.push('WhatsApp pairing phone number must be digits only in international format.');
      }
      const defaultChat = getChannelExtraValue(channel, draft, 'default_chat_id');
      if (defaultChat && !(/^\d{7,20}$/.test(defaultChat) || /^\d{7,20}@(s\.whatsapp\.net|g\.us)$/.test(defaultChat))) {
        errors.push('WhatsApp default chat must be a phone number or WhatsApp JID.');
      }
    }
    if (channel.name === 'signal') {
      const phone = getChannelSecretValue(channel, draft);
      const recipient = getChannelExtraValue(channel, draft, 'default_recipient');
      if (phone && !/^\+\d{7,15}$/.test(phone)) errors.push('Signal phone number must be in E.164 format.');
      if (recipient && !/^\+\d{7,15}$/.test(recipient)) errors.push('Signal default recipient must be in E.164 format.');
    }

    return errors;
  };

  const channelConfiguredForDraft = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    const extra = asRecord(channel.extra);
    const tokenPresent = channel.name === 'whatsapp'
      ? Boolean(getWhatsAppAuthDir(channel, draft))
      : Boolean(getChannelSecretValue(channel, draft) || channel.token_present);
    if (channel.name === 'slack') {
      return tokenPresent && Boolean(String(draft.extra.slack_app || '').trim() || extra.app_token_present) && channelValidationErrorsForDraft(channel, draft).length === 0;
    }
    return tokenPresent && channelValidationErrorsForDraft(channel, draft).length === 0;
  };

  const channelPairedForDraft = (channel: ChannelSnapshot) => {
    const extra = asRecord(channel.extra);
    const pairPayload = channelPairPayloads[channel.name];
    return Boolean(pairPayload?.paired || channel.paired || extra.paired);
  };

  const channelReadyForDraft = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    if (!channelConfiguredForDraft(channel, draft)) return false;
    if (channel.name === 'whatsapp') return Boolean(getWhatsAppAuthDir(channel, draft) && channelPairedForDraft(channel));
    return true;
  };

  const channelEnablementHint = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    const validationErrors = channelValidationErrorsForDraft(channel, draft);
    if (validationErrors.length > 0) return validationErrors[0];
    if (channel.name === 'whatsapp') {
      const authDir = getWhatsAppAuthDir(channel, draft);
      if (!authDir) return 'Pick or save an auth directory first.';
      if (!channelPairedForDraft(channel)) return 'Generate and scan a WhatsApp QR code before enabling.';
      return 'Ready to enable after restart.';
    }
    if (channel.name === 'slack' && !String(draft.extra.slack_app || '').trim() && !asRecord(channel.extra).app_token_present) {
      return 'Add the Slack app token for Socket Mode before enabling.';
    }
    if (!channelConfiguredForDraft(channel, draft)) return 'Complete the required credential first.';
    return 'Ready to enable after restart.';
  };

  const channelHasUnsavedChanges = (channel: ChannelSnapshot, draft: ChannelDraft) => {
    const extra = asRecord(channel.extra);
    if (draft.enabled !== channel.enabled) return true;
    if ((draft.trust_mode || '') !== (channel.trust_mode || '')) return true;
    if (channel.name === 'whatsapp') {
      const currentAuthDir = String(extra.auth_dir || extra.default_auth_dir || '').trim();
      if (getWhatsAppAuthDir(channel, draft) !== currentAuthDir) return true;
    } else if (Boolean(String(draft.secret || '').trim())) {
      return true;
    }
    if (channel.name === 'slack' && Boolean(String(draft.extra.slack_app || '').trim())) return true;
    for (const field of channel.fields || []) {
      if (field.key === 'secret') continue;
      const draftValue = String(draft.extra[field.key] ?? '');
      const currentValue = String(extra[field.key] ?? '');
      if (field.kind === 'boolean') {
        if (Boolean(draft.extra[field.key]) !== Boolean(extra[field.key])) return true;
      } else if (draftValue && draftValue !== currentValue) {
        return true;
      }
    }
    return false;
  };

  const syncProviderState = (parsed: Record<string, any>) => {
    const providers = parsed.providers || {};
    const providerId = resolveConfiguredProviderId(parsed);
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

  const refreshIntegrations = async () => {
    try {
      const snapshot = await getDesktopIntegrations();
      setIntegrations(snapshot.integrations || []);
    } catch {
      setIntegrations([]);
    }
  };

  const refreshRuntimeSkills = async () => {
    try {
      const snapshot = await getSkills();
      setRuntimeSkills(snapshot || []);
    } catch {
      setRuntimeSkills([]);
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
      refreshIntegrations(),
      refreshRuntimeSkills(),
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
        if (updates.tts || updates.features) invalidateVoiceAssistantCache();
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

  const allowedTools = useMemo(() => {
    const policy = asRecord(config.policy);
    const tools = policy.allowed_tools;
    return Array.isArray(tools) ? tools.map((tool) => String(tool)) : [];
  }, [config]);

  const selfConfigAllowed = SELF_CONFIG_TOOLS.every((tool) => allowedTools.includes(tool));
  const forgeToolsAllowed = FORGE_TOOLS.every((tool) => allowedTools.includes(tool));
  const desktopAutonomousExecution = Boolean(asRecord(config.desktop).autonomous_execution);
  const configuredAutonomyProfile = getAutonomyProfileById(String(asRecord(config.desktop).autonomy_profile || ''));

  const loadedSkillNames = useMemo(() => new Set(runtimeSkills.map((skill) => skill.name)), [runtimeSkills]);
  const featureKeySet = useMemo(() => new Set(Object.keys(features)), [features]);
  const groupedFeatureSections = useMemo(() => {
    const used = new Set<string>();
    const groups = FEATURE_GROUPS.map((group) => {
      const entries = group.keys
        .filter((key) => featureKeySet.has(key))
        .map((key) => {
          used.add(key);
          return [key, features[key]] as const;
        });
      return { title: group.title, entries };
    }).filter((group) => group.entries.length > 0);
    const remaining = Object.entries(features).filter(([key]) => !used.has(key));
    if (remaining.length > 0) groups.push({ title: 'Other', entries: remaining });
    return groups;
  }, [featureKeySet, features]);

  const setToolBundleEnabled = async (tools: readonly string[], enabled: boolean, successText: string) => {
    setAutonomySaving(true);
    setMsg(null);
    try {
      const nextAllowed = new Set(allowedTools);
      for (const tool of tools) {
        if (enabled) nextAllowed.add(tool);
        else nextAllowed.delete(tool);
      }
      await save({
        policy: {
          ...asRecord(config.policy),
          allowed_tools: Array.from(nextAllowed),
        },
      });
      await Promise.all([refreshConfig(), refreshRuntimeSkills()]);
      setMsg({ ok: true, text: successText });
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to update agent autonomy permissions.' });
    } finally {
      setAutonomySaving(false);
    }
  };

  const saveAutonomyProfile = async (profileId: string) => {
    const profile = getAutonomyProfileById(profileId);
    setAutonomySaving(true);
    setMsg(null);
    try {
      await save({
        desktop: {
          ...asRecord(config.desktop),
          autonomy_profile: profile.id,
          autonomous_execution: profile.mode === 'auto-run-low-risk' || profile.mode === 'policy-driven-autonomous',
          enabled:
            profile.mode === 'auto-run-low-risk' || profile.mode === 'policy-driven-autonomous'
              ? true
              : Boolean(asRecord(config.desktop).enabled),
        },
        features: {
          ...asRecord(config.features),
          desktop:
            profile.mode === 'auto-run-low-risk' || profile.mode === 'policy-driven-autonomous'
              ? true
              : Boolean(asRecord(config.features).desktop),
        },
      });
      await refreshConfig();
      setMsg({ ok: true, text: `${profile.label} is now the visible autonomy profile for the desktop shell.` });
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to save autonomy profile.' });
    } finally {
      setAutonomySaving(false);
    }
  };

  const saveAssistantCapability = async (
    featureKey: AssistantCapability,
    configSection: 'desktop' | 'browser' | 'tts',
    enabled: boolean,
  ) => {
    setAssistantSaving((current) => ({ ...current, [featureKey]: true }));
    try {
      const currentFeatures = asRecord(config.features);
      const currentSection = asRecord(config[configSection]);
      await save({
        features: { ...currentFeatures, [featureKey]: enabled },
        [configSection]: { ...currentSection, enabled },
      });
      await refreshFeatures();
      await refreshConfig();
    } finally {
      setAssistantSaving((current) => ({ ...current, [featureKey]: false }));
    }
  };

  const assistantFeatureEnabled = (featureKey: AssistantCapability) => {
    if (typeof features[featureKey]?.value === 'boolean') return Boolean(features[featureKey].value);
    return Boolean(asRecord(config.features)[featureKey]);
  };

  const assistantCapabilityState = (
    featureKey: AssistantCapability,
    configSection: 'desktop' | 'browser' | 'tts',
  ) => {
    const featureEnabled = assistantFeatureEnabled(featureKey);
    const sectionEnabled = Boolean(asRecord(config[configSection]).enabled);
    const enabled = featureEnabled && sectionEnabled;
    const pending = assistantSaving[featureKey];
    const status = enabled ? 'Live' : pending ? 'Applying' : (featureEnabled || sectionEnabled) ? 'Syncing' : 'Off';
    return {
      enabled,
      pending,
      featureEnabled,
      sectionEnabled,
      status,
      tone: enabled ? 'live' : pending ? 'syncing' : (featureEnabled || sectionEnabled) ? 'warning' : 'idle',
    };
  };

  const voiceCapability = assistantCapabilityState('voice', 'tts');
  const desktopCapability = assistantCapabilityState('desktop', 'desktop');
  const browserCapability = assistantCapabilityState('browser', 'browser');
  const enabledFeatureCount = Object.values(features).filter((entry) => entry.value).length;
  const liveIntegrationCount = integrations.filter((integration) => integration.connected).length;

  const captureScreenPreview = async () => {
    setAssistantScreenBusy(true);
    setMsg(null);
    try {
      const result = await captureAssistantScreen();
      if (!result.ok || !result.data_url) {
        throw new Error(result.error || 'Failed to capture the current screen.');
      }
      setAssistantScreen({
        dataUrl: result.data_url,
        width: Number(result.width || 0),
        height: Number(result.height || 0),
        monitor: Number(result.monitor || 0),
      });
      setMsg({ ok: true, text: 'Captured live screen preview for the assistant.' });
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to capture the current screen.' });
    } finally {
      setAssistantScreenBusy(false);
    }
  };

  const previewVoice = async () => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      setMsg({ ok: false, text: 'Speech synthesis is not available in this desktop runtime.' });
      return;
    }

    const ttsConfig = asRecord(config.tts);
    const requestedVoice = String(ttsConfig.voice || '').trim().toLowerCase();
    const rate = Math.min(2, Math.max(0.6, Number(ttsConfig.speed || 1)));
    const utterance = new SpeechSynthesisUtterance(
      'NeuralClaw premium assistant online. I can speak, listen, and inspect your screen when you ask.',
    );
    utterance.rate = rate;

    setVoicePreviewBusy(true);
    try {
      const synth = window.speechSynthesis;
      const applyVoice = () => {
        const voices = synth.getVoices();
        const matched = voices.find((voice) => {
          const name = voice.name.toLowerCase();
          const uri = voice.voiceURI.toLowerCase();
          return requestedVoice && (name === requestedVoice || uri === requestedVoice || name.includes(requestedVoice) || uri.includes(requestedVoice));
        });
        if (matched) utterance.voice = matched;
        synth.cancel();
        synth.speak(utterance);
      };

      if (synth.getVoices().length > 0) {
        applyVoice();
      } else {
        await new Promise<void>((resolve) => {
          const timeout = window.setTimeout(resolve, 700);
          synth.onvoiceschanged = () => {
            window.clearTimeout(timeout);
            resolve();
          };
        });
        applyVoice();
      }
      setMsg({ ok: true, text: 'Voice preview started.' });
    } catch (error: any) {
      setMsg({ ok: false, text: error?.message || 'Failed to preview voice.' });
    } finally {
      window.setTimeout(() => setVoicePreviewBusy(false), 600);
    }
  };

  const restartBackendNow = async () => {
    setMsg(null);
    try {
      try {
        await invoke('stop_backend');
      } catch {
        // Backend may already be stopped.
      }
      // Wait for old sidecar to fully die and release port 8080.
      await new Promise((resolve) => window.setTimeout(resolve, 3000));
      await invoke('start_backend');
      await new Promise((resolve) => window.setTimeout(resolve, 3000));
      await Promise.all([refreshBackendStatus(), refreshFeatures(), refreshIntegrations(), refreshMemoryStats(), refreshChannels(), refreshConfig()]);
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

  const persistChannelDraft = async (
    channelName: string,
    draft: ChannelDraft,
    options: PersistChannelOptions = {},
  ) => {
    if (!draft) return;
    const snapshot = channels.find((entry) => entry.name === channelName);
    const nextDraft: ChannelDraft = {
      ...draft,
      secret: draft.secret,
      extra: { ...(draft.extra || {}) },
    };
    if (channelName === 'whatsapp') {
      const authDir = getWhatsAppAuthDir(
        snapshot || {
          name: 'whatsapp',
          label: 'WhatsApp',
          description: '',
          enabled: false,
          configured: false,
          running: false,
          trust_mode: '',
          token_present: false,
          restart_required: true,
          extra: {},
        },
        nextDraft,
      );
      nextDraft.secret = authDir;
      nextDraft.extra = { ...nextDraft.extra, auth_dir: authDir };
    }
    setChannelSaving((current) => ({ ...current, [channelName]: true }));
    if (!options.silentResult) {
      setChannelResults((current) => ({ ...current, [channelName]: null }));
    }
    try {
      const result = await updateChannel(channelName, nextDraft);
      if (!result.ok) {
        if (!options.silentResult) {
          setChannelResults((current) => ({
            ...current,
            [channelName]: { ok: false, text: result.error || 'Failed to save channel.' },
          }));
        }
        return;
      }
      setRestartRequired(true);
      if (!options.silentResult) {
        setChannelResults((current) => ({
          ...current,
          [channelName]: {
            ok: true,
            text: options.successText || 'Saved. Restart the backend to apply channel changes.',
          },
        }));
      }
      await refreshChannels();
    } catch (error: any) {
      if (!options.silentResult) {
        setChannelResults((current) => ({
          ...current,
          [channelName]: { ok: false, text: error?.message || 'Failed to save channel.' },
        }));
      }
    } finally {
      setChannelSaving((current) => ({ ...current, [channelName]: false }));
    }
  };

  const saveChannelConfig = async (channelName: string, draftOverride?: ChannelDraft, options?: PersistChannelOptions) => {
    const draft = draftOverride || channelDrafts[channelName];
    if (!draft) return;
    await persistChannelDraft(channelName, draft, options);
  };

  const testChannelConfig = async (channelName: string) => {
    const snapshot = channels.find((entry) => entry.name === channelName);
    const draft = channelDrafts[channelName];
    if (!draft) return;
    setChannelTesting((current) => ({ ...current, [channelName]: true }));
    setChannelResults((current) => ({ ...current, [channelName]: null }));
    try {
      const payload = channelName === 'whatsapp' && snapshot
        ? {
            ...draft,
            secret: getWhatsAppAuthDir(snapshot, draft),
            extra: { ...draft.extra, auth_dir: getWhatsAppAuthDir(snapshot, draft) },
          }
        : draft;
      const result = await testChannel(channelName, payload);
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
    const snapshot = channels.find((entry) => entry.name === channelName);
    const draft = channelDrafts[channelName];
    if (!draft) return;
    let pairingDraft = draft;
    if (snapshot && channelName === 'whatsapp') {
      const preparedDraft: ChannelDraft = {
        ...draft,
        secret: getWhatsAppAuthDir(snapshot, draft),
        extra: { ...draft.extra, auth_dir: getWhatsAppAuthDir(snapshot, draft) },
      };
      pairingDraft = preparedDraft;
      await persistChannelDraft(channelName, preparedDraft, { silentResult: true });
    }
    setChannelPairing((current) => ({ ...current, [channelName]: true }));
    setChannelResults((current) => ({ ...current, [channelName]: null }));
    setChannelPairPayloads((current) => ({ ...current, [channelName]: null }));
    try {
      const result = await pairChannel(channelName, pairingDraft);
      setChannelResults((current) => ({
        ...current,
        [channelName]: {
          ok: result.ok,
          text: result.ok
            ? (result.message || (result.paired ? 'Already paired.' : result.pairing_code ? `Enter code on your phone: ${result.pairing_code}` : 'QR generated. Scan it on your phone.'))
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
            pairingCode: result.pairing_code,
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
        await refreshChannels();
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

  const resetChannelConfig = async (channelName: string) => {
    if (!window.confirm(`Reset ${channelName} channel? This will clear all saved config and credentials. For WhatsApp, this also deletes pairing data so you can re-pair fresh.`)) {
      return;
    }
    setChannelResetting((current) => ({ ...current, [channelName]: true }));
    setChannelResults((current) => ({ ...current, [channelName]: null }));
    setChannelPairPayloads((current) => ({ ...current, [channelName]: null }));
    try {
      const result = await resetChannel(channelName);
      setChannelResults((current) => ({
        ...current,
        [channelName]: {
          ok: result.ok,
          text: result.ok ? 'Channel reset successfully.' : (result.error || 'Reset failed.'),
        },
      }));
      await refreshChannels();
    } catch (error: any) {
      setChannelResults((current) => ({
        ...current,
        [channelName]: { ok: false, text: error?.message || 'Reset failed.' },
      }));
    } finally {
      setChannelResetting((current) => ({ ...current, [channelName]: false }));
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

  const cloudProviders = ALL_PROVIDERS.filter((p) => !isLocalProvider(p.id));
  const localProviders = ALL_PROVIDERS.filter((p) => isLocalProvider(p.id));

  const renderProviderCards = (providers: typeof ALL_PROVIDERS) =>
    providers.map((provider) => {
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
          {selected && <div className="check-badge">OK</div>}
          <div className="provider-icon" style={{ background: colors.bg, color: colors.text }}>
            {colors.icon}
          </div>
          <div className="provider-name">{provider.name}</div>
          <div className="provider-company">{provider.company}</div>
        </button>
      );
    });

  const providerCardGrid = (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)', marginBottom: 8 }}>
        Cloud Providers - API key required
      </div>
      <div className="provider-grid" style={{ marginBottom: 14 }}>
        {renderProviderCards(cloudProviders)}
      </div>
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)', marginBottom: 8 }}>
        Local Providers - runs on your machine, no API key
      </div>
      <div className="provider-grid">
        {renderProviderCards(localProviders)}
      </div>
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
          <section className="settings-command-deck">
            <div>
              <div className="eyebrow">Desktop Control Surface</div>
              <h2>Configure runtime behavior, trust rails, and premium product slices</h2>
              <p>
                Settings is the operator-level surface for routing models, enabling capabilities, and deciding how much real-world access the assistant should have.
              </p>
            </div>
            <div className="settings-command-stats">
              <div className="settings-command-stat">
                <span>Section</span>
                <strong>{section}</strong>
              </div>
              <div className="settings-command-stat">
                <span>Features live</span>
                <strong>{enabledFeatureCount}</strong>
              </div>
              <div className="settings-command-stat">
                <span>Integrations</span>
                <strong>{liveIntegrationCount}</strong>
              </div>
            </div>
          </section>

          {msg && (
            <div
              className="info-box"
              style={{
                marginBottom: 14,
                background: msg.ok ? 'var(--accent-green-muted)' : 'var(--accent-red-muted)',
                borderColor: msg.ok ? 'rgba(63, 185, 80, 0.3)' : 'rgba(248, 81, 73, 0.3)',
              }}
            >
              <span className="info-icon">{msg.ok ? 'OK' : '!'}</span>
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
              <IntegrationOverview integrations={integrations} />
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
              <div className="settings-row" style={{ borderTop: '1px solid var(--border)', marginTop: 12, paddingTop: 16 }}>
                <div>
                  <div className="settings-row-label">Reset Setup Wizard</div>
                  <div className="settings-row-desc">Re-run the first-time setup wizard. Clears provider/model choices but keeps your chat history and memory.</div>
                </div>
                <button
                    className="btn btn-secondary btn-sm"
                    style={{ color: '#f87171', borderColor: '#f87171' }}
                    onClick={() => {
                      if (window.confirm('Re-run the setup wizard? Your chat history and memory data are preserved.')) {
                        void Promise.all([
                          deletePersistedValue('neuralclaw_setup_complete'),
                          deletePersistedValue('neuralclaw_current_view'),
                        ]).finally(() => {
                          window.location.reload();
                        });
                      }
                    }}
                  >
                  Reset Setup
                </button>
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
              <ModelRolesPicker config={config} saveSectionPatch={saveSectionPatch} />
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
                Configure Telegram, Discord, Slack, WhatsApp, and Signal from a guided desktop control plane. Save credentials first, then pair or test, then enable the channel.
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
                  const fieldSpecs = channel.fields || [];
                  const secretSpec = fieldSpecs.find((field) => field.key === 'secret');
                  const nonSecretFields = fieldSpecs.filter((field) => field.key !== 'secret');
                  const result = channelResults[channel.name];
                  const pairPayload = channelPairPayloads[channel.name];
                  const isWhatsApp = channel.name === 'whatsapp';
                  const effectiveAuthDir = isWhatsApp ? getWhatsAppAuthDir(channel, draft) : '';
                  const ready = channelReadyForDraft(channel, draft);
                  const configured = channelConfiguredForDraft(channel, draft);
                  const paired = channelPairedForDraft(channel);
                  const canEnable = ready;
                  const dirty = channelHasUnsavedChanges(channel, draft);
                  const statusText = channel.status
                    ? channel.status.replace(/_/g, ' ')
                    : channel.running
                      ? 'running'
                      : ready
                        ? 'ready'
                        : configured
                          ? 'saved'
                          : 'needs config';
                  const statusTone = channel.status === 'needs_config'
                    ? 'badge-red'
                    : channel.status === 'needs_pairing'
                      ? 'badge-orange'
                      : channel.running
                        ? 'badge-green'
                        : 'badge-blue';
                  return (
                    <div key={channel.name} className="card" style={{ marginBottom: 16 }}>
                      <div className="card-header">
                        <div>
                          <span className="card-title">{channel.label}</span>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>{channel.description}</div>
                        </div>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                          <span className={`badge ${statusTone}`}>
                            {statusText}
                          </span>
                          <span className={`badge ${configured ? 'badge-orange' : 'badge-red'}`}>
                            {configured ? 'Configured' : 'Needs Setup'}
                          </span>
                          <span className={`badge ${canEnable ? 'badge-green' : 'badge-blue'}`}>
                            {canEnable ? 'Can Enable' : 'Setup Required'}
                          </span>
                          <span className={`badge ${channel.running ? 'badge-green' : 'badge-blue'}`}>
                            {channel.running ? 'Live' : 'Restart Pending'}
                          </span>
                        </div>
                      </div>

                      <div className="channel-status-strip">
                        <div className={`channel-status-card ${configured ? 'is-good' : 'is-pending'}`}>
                          <span className="channel-status-label">Credentials</span>
                          <span className="channel-status-value">{configured ? 'Saved' : 'Missing'}</span>
                        </div>
                        {isWhatsApp && (
                          <div className={`channel-status-card ${paired ? 'is-good' : 'is-pending'}`}>
                            <span className="channel-status-label">Pairing</span>
                            <span className="channel-status-value">{paired ? 'Linked' : 'Scan QR'}</span>
                          </div>
                        )}
                        <div className={`channel-status-card ${canEnable ? 'is-good' : 'is-pending'}`}>
                          <span className="channel-status-label">Activation</span>
                          <span className="channel-status-value">{canEnable ? 'Ready' : 'Blocked'}</span>
                        </div>
                      </div>
                      <div className="channel-hint-text">{channel.status_detail || channelEnablementHint(channel, draft)}</div>

                      <div className="settings-row">
                        <div>
                          <div className="settings-row-label">Enabled</div>
                          <div className="settings-row-desc">
                            Register this channel when the backend starts. The toggle saves immediately and refuses incomplete setup.
                          </div>
                        </div>
                        <button
                          className={`toggle ${draft.enabled ? 'on' : ''}`}
                          onClick={() => {
                            const nextEnabled = !draft.enabled;
                            if (nextEnabled && !canEnable) {
                              setChannelResults((current) => ({
                                ...current,
                                [channel.name]: { ok: false, text: channelEnablementHint(channel, draft) },
                              }));
                              return;
                            }
                            const nextDraft = { ...draft, enabled: nextEnabled };
                            updateChannelDraft(channel.name, () => nextDraft);
                            void saveChannelConfig(channel.name, nextDraft, {
                              successText: nextEnabled
                                ? `${channel.label} will enable after the next backend restart.`
                                : `${channel.label} disabled. Restart the backend to unload it from runtime.`,
                            });
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
                            const nextDraft = { ...draft, trust_mode: value };
                            updateChannelDraft(channel.name, () => nextDraft);
                            void saveChannelConfig(channel.name, nextDraft, {
                              successText: `${channel.label} trust mode saved. Restart the backend to apply it.`,
                            });
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
                          <div className="settings-row-label">{secretSpec?.label || meta.secretLabel}</div>
                          <div className="settings-row-desc">{secretSpec?.description || meta.hint}</div>
                        </div>
                        <div style={{ width: 400 }}>
                          <input
                            className="input-field input-mono"
                            type={channel.name === 'whatsapp' ? 'text' : 'password'}
                            value={String(channel.name === 'whatsapp' ? effectiveAuthDir : draft.secret)}
                            placeholder={secretSpec?.placeholder || meta.placeholder}
                            onChange={(event) => {
                              const value = event.target.value;
                              updateChannelDraft(channel.name, (current) => ({
                                ...current,
                                secret: value,
                                extra: channel.name === 'whatsapp'
                                  ? { ...current.extra, auth_dir: value }
                                  : current.extra,
                              }));
                            }}
                          />
                        </div>
                      </div>

                      {nonSecretFields.map((field) => (
                        field.kind === 'boolean' ? (
                          <div key={field.key} className="settings-row">
                            <div>
                              <div className="settings-row-label">{field.label}</div>
                              <div className="settings-row-desc">{field.description}</div>
                            </div>
                            <button
                              className={`toggle ${Boolean(draft.extra[field.key] ?? asRecord(channel.extra)[field.key]) ? 'on' : ''}`}
                              onClick={() => {
                                const nextDraft = {
                                  ...draft,
                                  extra: {
                                    ...draft.extra,
                                    [field.key]: !Boolean(draft.extra[field.key] ?? asRecord(channel.extra)[field.key]),
                                  },
                                };
                                updateChannelDraft(channel.name, () => nextDraft);
                                void saveChannelConfig(channel.name, nextDraft, {
                                  successText: `${channel.label} ${field.label.toLowerCase()} saved. Restart the backend to apply it.`,
                                });
                              }}
                            />
                          </div>
                        ) : (
                          <div key={field.key} className="settings-row">
                            <div>
                              <div className="settings-row-label">{field.label}</div>
                              <div className="settings-row-desc">{field.description}</div>
                            </div>
                            <div style={{ width: 400 }}>
                              <input
                                className="input-field input-mono"
                                type={field.kind === 'secret-extra' ? 'password' : 'text'}
                                value={String(draft.extra[field.key] || asRecord(channel.extra)[field.key] || '')}
                                placeholder={field.placeholder || ''}
                                onChange={(event) => {
                                  const rawValue = event.target.value;
                                  const value = channel.name === 'whatsapp' && field.key === 'phone_number'
                                    ? rawValue.replace(/[^0-9]/g, '')
                                    : rawValue;
                                  updateChannelDraft(channel.name, (current) => ({
                                    ...current,
                                    extra: { ...current.extra, [field.key]: value },
                                  }));
                                }}
                              />
                            </div>
                          </div>
                        )
                      ))}

                      {isWhatsApp && (
                        <>
                          <div className="channel-step-row">
                            <div className={`channel-step ${effectiveAuthDir ? 'done' : 'current'}`}>1. Save auth directory</div>
                            <div className={`channel-step ${(pairPayload?.qrDataUrl || pairPayload?.qrData || pairPayload?.pairingCode || paired) ? 'current' : 'pending'} ${paired ? 'done' : ''}`}>2. Pair</div>
                            <div className={`channel-step ${paired ? 'done' : 'pending'}`}>3. Test pairing</div>
                            <div className={`channel-step ${draft.enabled ? 'done' : (canEnable ? 'current' : 'pending')}`}>4. Enable</div>
                          </div>
                        </>
                      )}

                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 16 }}>
                        <button
                          className="btn btn-primary"
                          onClick={() => { void saveChannelConfig(channel.name, draft, {
                            successText: `${channel.label} setup saved. Restart the backend after you finish pairing or testing.`,
                          }); }}
                          disabled={Boolean(channelSaving[channel.name])}
                        >
                          {channelSaving[channel.name] ? 'Saving...' : dirty ? 'Save Setup' : 'Save Channel'}
                        </button>
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
                            {channelPairing[channel.name]
                              ? 'Pairing...'
                              : paired
                                ? 'Refresh Pairing'
                                : draft.extra.phone_number ? 'Get Pairing Code' : 'Generate QR'}
                          </button>
                        )}
                        <button
                          className="btn btn-secondary"
                          style={{ marginLeft: 'auto', color: 'var(--text-danger, #f44)' }}
                          onClick={() => { void resetChannelConfig(channel.name); }}
                          disabled={Boolean(channelResetting[channel.name])}
                        >
                          {channelResetting[channel.name] ? 'Resetting...' : 'Reset'}
                        </button>
                      </div>

                      {result && (
                        <div className={`info-box ${result.ok ? 'success' : 'error'}`} style={{ marginTop: 12 }}>
                          <span className="info-icon">{result.ok ? 'OK' : '!'}</span>
                          <span>{result.text}</span>
                        </div>
                      )}

                      {channel.name === 'whatsapp' && pairPayload && (
                        <div className="channel-qr-panel" style={{ marginTop: 14 }}>
                          <div className="card-title" style={{ marginBottom: 8 }}>WhatsApp Pairing</div>
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                            {pairPayload.paired
                              ? 'This auth directory is already paired. Test the channel, then enable it when you are ready.'
                              : pairPayload.pairingCode
                                ? 'Enter the code below on your phone: WhatsApp -> Linked Devices -> Link with phone number.'
                                : 'Scan the QR code in WhatsApp -> Linked Devices -> Link a Device. Then click the pair button again or Test to confirm the link.'}
                          </div>
                          {pairPayload.authDir && (
                            <div className="channel-auth-path">
                              {pairPayload.authDir}
                            </div>
                          )}
                          {pairPayload.pairingCode ? (
                            <div style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              padding: '20px 0',
                            }}>
                              <div style={{
                                fontSize: 36,
                                fontWeight: 700,
                                fontFamily: 'var(--font-mono)',
                                letterSpacing: '0.25em',
                                color: 'var(--accent-primary)',
                                background: 'rgba(47, 129, 247, 0.08)',
                                border: '2px solid rgba(47, 129, 247, 0.3)',
                                borderRadius: 16,
                                padding: '16px 32px',
                                userSelect: 'all',
                              }}>
                                {pairPayload.pairingCode}
                              </div>
                            </div>
                          ) : pairPayload.qrDataUrl ? (
                            <img
                              src={pairPayload.qrDataUrl}
                              alt="WhatsApp pairing QR"
                              style={{ width: 260, height: 260, borderRadius: 18, background: '#fff', padding: 14 }}
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
                  <div className="stat-card">
                    <div className="stat-label">Vector</div>
                    <div className="stat-value">{memoryStats?.vector_count ?? '-'}</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Identity</div>
                    <div className="stat-value">{memoryStats?.identity_count ?? '-'}</div>
                  </div>
                </div>
              </div>

              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-header">
                  <span className="card-title">Memory Feature Flags</span>
                </div>
                {Object.entries(features)
                  .filter(([key]) => ['vector_memory', 'identity', 'semantic_memory', 'procedural_memory', 'evolution'].includes(key))
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

              <EmbedModelPicker config={config} saveSectionPatch={saveSectionPatch} />

              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-header">
                  <span className="card-title">Retention Policy</span>
                </div>
                {[
                  ['episodic_retention_days', 'Episodic'],
                  ['semantic_retention_days', 'Semantic'],
                  ['procedural_retention_days', 'Procedural'],
                  ['vector_retention_days', 'Vector'],
                  ['identity_retention_days', 'Identity'],
                ].map(([key, label]) => (
                  <div key={key} className="settings-row">
                    <div>
                      <div className="settings-row-label">{label} retention</div>
                      <div className="settings-row-desc">Auto-expire stale {label.toLowerCase()} memory after this many days.</div>
                    </div>
                    <input
                      className="input-field"
                      style={{ width: 120 }}
                      type="number"
                      min={1}
                      defaultValue={config.memory?.[key] || 30}
                      onBlur={(event) => {
                        const value = Math.max(1, Number(event.target.value || 30));
                        saveSectionPatch('memory', { [key]: value });
                      }}
                    />
                  </div>
                ))}
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Cleanup interval</div>
                    <div className="settings-row-desc">How often hot paths trigger automatic retention cleanup.</div>
                  </div>
                  <input
                    className="input-field"
                    style={{ width: 120 }}
                    type="number"
                    min={30}
                    defaultValue={config.memory?.retention_cleanup_interval_seconds || 300}
                    onBlur={(event) => {
                      const value = Math.max(30, Number(event.target.value || 300));
                      saveSectionPatch('memory', { retention_cleanup_interval_seconds: value });
                    }}
                  />
                </div>
                <div className="memory-editor-actions">
                  <button className="btn btn-secondary btn-sm" onClick={() => {
                    void (async () => {
                      try {
                        const result = await runMemoryRetention();
                        setMsg({ ok: true, text: `Retention cleanup deleted: ${JSON.stringify(result.deleted || {})}` });
                        await refreshMemoryStats();
                      } catch (error: any) {
                        setMsg({ ok: false, text: error?.message || 'Failed to run memory retention.' });
                      }
                    })();
                  }}>
                    Run Cleanup Now
                  </button>
                </div>
              </div>

              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-header">
                  <span className="card-title">Backup</span>
                </div>
                <input
                  className="input-field"
                  type="password"
                  placeholder="Optional passphrase"
                  value={memoryBackupPassphrase}
                  onChange={(event) => setMemoryBackupPassphrase(event.target.value)}
                  style={{ marginBottom: 12 }}
                />
                <textarea
                  className="input-field"
                  placeholder="Exported backup payload will appear here. Paste a payload here to import it."
                  value={memoryBackupPayload}
                  onChange={(event) => setMemoryBackupPayload(event.target.value)}
                  style={{ minHeight: 160, marginBottom: 12 }}
                />
                <div className="memory-editor-actions">
                  <button className="btn btn-secondary btn-sm" onClick={() => {
                    void (async () => {
                      try {
                        const exported = await exportMemoryBackup({ passphrase: memoryBackupPassphrase || undefined });
                        setMemoryBackupPayload(JSON.stringify(exported, null, 2));
                        setMsg({ ok: true, text: exported.encrypted ? 'Encrypted memory backup exported.' : 'Memory backup exported.' });
                      } catch (error: any) {
                        setMsg({ ok: false, text: error?.message || 'Failed to export memory backup.' });
                      }
                    })();
                  }}>
                    Export Backup
                  </button>
                  <button className="btn btn-secondary btn-sm" onClick={() => {
                    void (async () => {
                      try {
                        const parsed = JSON.parse(memoryBackupPayload || '{}') as { payload?: string; encrypted?: boolean; salt?: string; digest?: string };
                        const imported = await importMemoryBackup({
                          payload: String(parsed.payload || ''),
                          encrypted: Boolean(parsed.encrypted),
                          salt: parsed.salt,
                          digest: parsed.digest,
                          passphrase: memoryBackupPassphrase || undefined,
                        });
                        if (!imported.ok) throw new Error(imported.error || 'Import failed.');
                        setMsg({ ok: true, text: `Memory backup imported: ${JSON.stringify(imported.imported || {})}` });
                        await refreshMemoryStats();
                      } catch (error: any) {
                        setMsg({ ok: false, text: error?.message || 'Failed to import memory backup.' });
                      }
                    })();
                  }}>
                    Import Backup
                  </button>
                </div>
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

          {section === 'Assistant' && (
            <div className="settings-section">
              <h2>Computer + Voice Assistant</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Bring the avatar, screen awareness, browser actions, and spoken responses into one premium control surface.
              </p>
              <div className="assistant-overview-grid">
                <div className={`assistant-overview-card ${voiceCapability.tone}`}>
                  <div className="assistant-overview-label">Voice</div>
                  <div className="assistant-overview-value">{voiceCapability.status}</div>
                  <div className="assistant-overview-desc">
                    {voiceCapability.enabled
                      ? 'Spoken replies and voice-aware avatar behavior are live.'
                      : 'Speech and voice presence are currently offline.'}
                  </div>
                </div>
                <div className={`assistant-overview-card ${desktopCapability.tone}`}>
                  <div className="assistant-overview-label">Desktop</div>
                  <div className="assistant-overview-value">{desktopCapability.status}</div>
                  <div className="assistant-overview-desc">
                    {desktopCapability.enabled
                      ? 'Screen capture and computer actions are available.'
                      : 'Desktop capture and computer control are currently offline.'}
                  </div>
                </div>
                <div className={`assistant-overview-card ${browserCapability.tone}`}>
                  <div className="assistant-overview-label">Browser</div>
                  <div className="assistant-overview-value">{browserCapability.status}</div>
                  <div className="assistant-overview-desc">
                    {browserCapability.enabled
                      ? 'Browser navigation and web execution are available.'
                      : 'Browser automation is currently offline.'}
                  </div>
                </div>
              </div>

              <div className="card assistant-card" style={{ marginBottom: 16 }}>
                <div className="assistant-card-header">
                  <div>
                    <div className="card-title">Avatar Presence</div>
                    <div className="assistant-card-subtitle">Keep the on-screen companion intentional, anchored, and easy to trust.</div>
                  </div>
                  <span className={`assistant-status-badge ${avatarVisible ? 'live' : 'idle'}`}>
                    {avatarVisible ? 'Visible' : 'Hidden'}
                  </span>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Avatar Mode</div>
                    <div className="settings-row-desc">Show or hide the floating companion window.</div>
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
                  <div className="assistant-inline-control assistant-slider-control">
                    <input
                      type="range"
                      min="0.5"
                      max="2"
                      step="0.1"
                      value={avatarScale}
                      onChange={(event) => { void setAvatarScale(Number(event.target.value)); }}
                      style={{ flex: 1 }}
                    />
                    <span className="assistant-mono-value">{avatarScale.toFixed(1)}x</span>
                  </div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Render Mode</div>
                    <div className="settings-row-desc">Auto balances startup and visuals, Lite skips 3D entirely, Full prefers the full animated scene.</div>
                  </div>
                  <select
                    className="input-field"
                    style={{ width: 180 }}
                    value={avatarRenderMode}
                    onChange={(event) => { void setAvatarRenderMode(event.target.value as any); }}
                  >
                    <option value="auto">Auto</option>
                    <option value="lite">Lite</option>
                    <option value="full">Full</option>
                  </select>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Custom VRM Model</div>
                    <div className="settings-row-desc">Upload a .vrm avatar file or keep the built-in assistant.</div>
                  </div>
                  <div className="assistant-upload-block">
                    <label className="btn btn-secondary btn-sm assistant-file-button">
                      Choose VRM
                      <input
                        type="file"
                        accept=".vrm"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) void saveModelFile(file);
                        }}
                      />
                    </label>
                    <span className="assistant-upload-caption">
                      {avatarModelPath || 'Built-in NeuralClaw avatar'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="card assistant-card" style={{ marginBottom: 16 }}>
                <div className="assistant-card-header">
                  <div>
                    <div className="card-title">Voice Assistant</div>
                    <div className="assistant-card-subtitle">Speech, preview, and reply playback should behave like one coherent voice layer.</div>
                  </div>
                  <span className={`assistant-status-badge ${voiceCapability.tone}`}>
                    {voiceCapability.status}
                  </span>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Voice Presence</div>
                    <div className="settings-row-desc">Enable spoken replies, voice-aware avatar behavior, and channel voice features.</div>
                  </div>
                  <button
                    className={`toggle ${voiceCapability.enabled ? 'on' : ''}`}
                    disabled={voiceCapability.pending || saving}
                    onClick={() => { void saveAssistantCapability('voice', 'tts', !voiceCapability.enabled); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Auto Speak Replies</div>
                    <div className="settings-row-desc">Read desktop assistant replies aloud and keep the avatar mouth synced during playback.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(asRecord(config.tts).auto_speak) ? 'on' : ''}`}
                    disabled={!voiceCapability.enabled || saving}
                    onClick={() => { saveSectionPatch('tts', { auto_speak: !Boolean(asRecord(config.tts).auto_speak) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Provider</div>
                    <div className="settings-row-desc">Select the speech backend profile for channels and future richer voice output.</div>
                  </div>
                  <select
                    className="input-field"
                    style={{ width: 200 }}
                    value={String(asRecord(config.tts).provider || 'edge-tts')}
                    disabled={!voiceCapability.enabled || saving}
                    onChange={(event) => { saveSectionPatch('tts', { provider: event.target.value }); }}
                  >
                    <option value="edge-tts">Edge TTS</option>
                    <option value="openai">OpenAI</option>
                    <option value="elevenlabs">ElevenLabs</option>
                    <option value="piper">Piper</option>
                  </select>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Voice Name</div>
                    <div className="settings-row-desc">Used for backend speech generation and matched loosely for desktop voice playback when possible.</div>
                  </div>
                  <input
                    className="input-field input-mono"
                    style={{ width: 240 }}
                    value={String(asRecord(config.tts).voice || '')}
                    disabled={!voiceCapability.enabled || saving}
                    onChange={(event) => setConfig((current) => ({
                      ...current,
                      tts: { ...asRecord(current.tts), voice: event.target.value },
                    }))}
                    onBlur={(event) => { saveSectionPatch('tts', { voice: event.target.value }); }}
                    placeholder="en-US-AriaNeural"
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Speech Speed</div>
                    <div className="settings-row-desc">Tune delivery from slower guidance to brisk assistant replies.</div>
                  </div>
                  <div className="assistant-inline-control assistant-slider-control">
                    <input
                      type="range"
                      min="0.7"
                      max="1.6"
                      step="0.05"
                      value={Number(asRecord(config.tts).speed || 1)}
                      disabled={!voiceCapability.enabled || saving}
                      onChange={(event) => setConfig((current) => ({
                        ...current,
                        tts: { ...asRecord(current.tts), speed: Number(event.target.value) },
                      }))}
                      onMouseUp={(event) => {
                        const target = event.target as HTMLInputElement;
                        saveSectionPatch('tts', { speed: Number(target.value) });
                      }}
                      style={{ flex: 1 }}
                    />
                    <span className="assistant-mono-value">
                      {Number(asRecord(config.tts).speed || 1).toFixed(2)}x
                    </span>
                  </div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Voice Preview</div>
                    <div className="settings-row-desc">Test the current desktop voice profile instantly. Voice input is also available directly from chat and the avatar overlay.</div>
                  </div>
                  <button className="btn btn-secondary btn-sm" onClick={() => { void previewVoice(); }} disabled={!voiceCapability.enabled || voicePreviewBusy}>
                    {voicePreviewBusy ? 'Speaking...' : 'Preview Voice'}
                  </button>
                </div>
              </div>

              <div className="card assistant-card">
                <div className="assistant-card-header">
                  <div>
                    <div className="card-title">Computer Vision + Control</div>
                    <div className="assistant-card-subtitle">Desktop actions, browser execution, and evidence capture stay aligned here.</div>
                  </div>
                  <div className="assistant-card-header-group">
                    <span className={`assistant-status-badge ${desktopCapability.tone}`}>
                      Desktop {desktopCapability.status}
                    </span>
                    <span className={`assistant-status-badge ${browserCapability.tone}`}>
                      Browser {browserCapability.status}
                    </span>
                  </div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Desktop Control</div>
                    <div className="settings-row-desc">Let the assistant see this machine through screenshots and act with mouse, keyboard, clipboard, and app launch tools.</div>
                  </div>
                  <button
                    className={`toggle ${desktopCapability.enabled ? 'on' : ''}`}
                    disabled={desktopCapability.pending || saving}
                    onClick={() => { void saveAssistantCapability('desktop', 'desktop', !desktopCapability.enabled); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Browser Automation</div>
                    <div className="settings-row-desc">Enable website navigation, page extraction, clicking, typing, and browser-based execution.</div>
                  </div>
                  <button
                    className={`toggle ${browserCapability.enabled ? 'on' : ''}`}
                    disabled={browserCapability.pending || saving}
                    onClick={() => { void saveAssistantCapability('browser', 'browser', !browserCapability.enabled); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Full Machine Access</div>
                    <div className="settings-row-desc">Allow shell execution and local file operations when desktop mode is enabled.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(asRecord(config.desktop).full_machine_access) ? 'on' : ''}`}
                    disabled={!desktopCapability.enabled || saving}
                    onClick={() => { saveSectionPatch('desktop', { full_machine_access: !Boolean(asRecord(config.desktop).full_machine_access) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Screenshot Evidence</div>
                    <div className="settings-row-desc">Capture before/after evidence around desktop actions for safer automation traces.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(asRecord(config.desktop).screenshot_on_action) ? 'on' : ''}`}
                    disabled={!desktopCapability.enabled || saving}
                    onClick={() => { saveSectionPatch('desktop', { screenshot_on_action: !Boolean(asRecord(config.desktop).screenshot_on_action) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Live Screen Peek</div>
                    <div className="settings-row-desc">Verify what the assistant can currently see from this machine.</div>
                  </div>
                  <button className="btn btn-secondary btn-sm" onClick={() => { void captureScreenPreview(); }} disabled={!desktopCapability.enabled || assistantScreenBusy}>
                    {assistantScreenBusy ? 'Capturing...' : 'Capture Screen'}
                  </button>
                </div>
                {assistantScreen?.dataUrl && (
                  <div className="assistant-screen-preview">
                    <img
                      src={assistantScreen.dataUrl}
                      alt="Assistant screen preview"
                      className="assistant-screen-preview-image"
                    />
                    <div className="assistant-screen-preview-meta">
                      Monitor {assistantScreen.monitor} | {assistantScreen.width} x {assistantScreen.height}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {section === 'Features' && (
            <div className="settings-section">
              <h2>Feature Flags</h2>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                Live features switch instantly. Everything else persists immediately and applies on the next backend restart.
              </p>
              <div className="info-box" style={{ marginBottom: 16 }}>
                <span className="info-icon">i</span>
                <span>
                  Use this page as the assistant's nervous system control panel. Core intelligence changes behavior, memory features affect recall, and autonomy controls decide whether the agent may reconfigure itself or forge new skills.
                </span>
              </div>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-header">
                  <span className="card-title">Agent Autonomy</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {runtimeSkills.length > 0 ? `${runtimeSkills.length} skills live` : 'Runtime inventory loading'}
                  </span>
                </div>
                <div style={{ padding: '12px 16px', display: 'grid', gap: 12 }}>
                  <div>
                    <div className="settings-row-label" style={{ marginBottom: 8 }}>Autonomy Profile</div>
                    <div className="settings-row-desc" style={{ marginBottom: 12 }}>
                      Pick the operating posture that balances friendliness, control, and execution speed. This makes the autonomy tradeoff visible across the desktop shell.
                    </div>
                    <div className="autonomy-profile-grid">
                      {AUTONOMY_PROFILES.map((profile) => {
                        const selected = configuredAutonomyProfile.id === profile.id;
                        return (
                          <button
                            key={profile.id}
                            type="button"
                            className={`autonomy-profile-card${selected ? ' active' : ''}`}
                            onClick={() => { void saveAutonomyProfile(profile.id); }}
                            disabled={autonomySaving}
                          >
                            <div className="autonomy-profile-top">
                              <span className="autonomy-profile-name">{profile.label}</span>
                              <span className={`badge ${selected ? 'badge-blue' : 'badge'}`}>
                                {selected ? 'Current' : profile.executionLabel}
                              </span>
                            </div>
                            <div className="autonomy-profile-body">{profile.description}</div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="settings-row">
                    <div>
                      <div className="settings-row-label">Self-Configuration</div>
                      <div className="settings-row-desc">
                        Lets the agent inspect features, change its own model roles, and enable or disable skill access when you explicitly ask it to.
                      </div>
                    </div>
                    <button
                      className={`toggle ${selfConfigAllowed ? 'on' : ''}`}
                      onClick={() => {
                        void setToolBundleEnabled(
                          SELF_CONFIG_TOOLS,
                          !selfConfigAllowed,
                          !selfConfigAllowed
                            ? 'Agent self-configuration is now allowed.'
                            : 'Agent self-configuration permissions were revoked.',
                        );
                      }}
                      disabled={autonomySaving}
                    />
                  </div>
                  <div className="settings-row">
                    <div>
                      <div className="settings-row-label">Skill Forging Tools</div>
                      <div className="settings-row-desc">
                        Controls whether the agent may scout for new capabilities and forge new skills from APIs, docs, libraries, or code when you ask.
                      </div>
                    </div>
                    <button
                      className={`toggle ${forgeToolsAllowed ? 'on' : ''}`}
                      onClick={() => {
                        void setToolBundleEnabled(
                          FORGE_TOOLS,
                          !forgeToolsAllowed,
                          !forgeToolsAllowed
                            ? 'Forge and scout tools are now allowed for the agent.'
                            : 'Forge and scout tool access was revoked.',
                        );
                      }}
                      disabled={autonomySaving || !features.skill_forge?.value}
                    />
                  </div>
                  <div className="settings-row">
                    <div>
                      <div className="settings-row-label">Desktop Autonomous Execution</div>
                      <div className="settings-row-desc">
                        When enabled, the desktop agent treats direct requests to operate the local app or machine as executable work, not just instructions to explain. Turning this on also enables Desktop Control in runtime config if it was off.
                      </div>
                    </div>
                    <button
                      className={`toggle ${desktopAutonomousExecution ? 'on' : ''}`}
                      onClick={() => {
                        const nextEnabled = !desktopAutonomousExecution;
                        void save({
                          desktop: {
                            ...asRecord(config.desktop),
                            enabled: nextEnabled ? true : Boolean(asRecord(config.desktop).enabled),
                            autonomous_execution: nextEnabled,
                          },
                          features: {
                            ...asRecord(config.features),
                            desktop: nextEnabled ? true : Boolean(asRecord(config.features).desktop),
                          },
                        });
                      }}
                      disabled={saving}
                    />
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Skill Forge feature: <strong>{features.skill_forge?.value ? 'enabled' : 'disabled'}</strong>
                    {' '}| Loaded skills: <strong>{runtimeSkills.length}</strong>
                    {' '}| Self-config skill: <strong>{loadedSkillNames.has('self_config') ? 'loaded' : 'not loaded'}</strong>
                    {' '}| Desktop autonomy: <strong>{desktopAutonomousExecution ? 'enabled' : 'disabled'}</strong>
                  </div>
                </div>
              </div>
              {Object.keys(features).length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">F</span>
                  <h3>No Feature Data</h3>
                  <p>Connect to the backend to manage feature flags.</p>
                </div>
              ) : (
                groupedFeatureSections.map((group) => (
                  <div key={group.title} className="card" style={{ marginBottom: 16 }}>
                    <div className="card-header">
                      <span className="card-title">{group.title}</span>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{group.entries.length} toggles</span>
                    </div>
                    <div style={{ padding: '6px 16px 12px' }}>
                      {group.entries.map(([key, feature]) => (
                        <div key={key} className="settings-row">
                          <div>
                            <div className="settings-row-label">{feature.label || formatMemoryLabel(key)}</div>
                            <div className="settings-row-desc">
                              {feature.live ? 'Takes effect immediately.' : 'Persists now and applies on backend restart.'}
                            </div>
                          </div>
                          <button
                            className={`toggle ${feature.value ? 'on' : ''}`}
                            onClick={() => { void toggleFeatureValue(key, !feature.value, feature.live); }}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {section === 'Advanced' && (
            <div className="settings-section">
              <h2>Advanced</h2>

              <SearchProvidersSettings config={config} onSave={save} />

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
                <div className="card-title" style={{ marginBottom: 14 }}>Automation Runtime</div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Shell Execution</div>
                    <div className="settings-row-desc">Allow the agent to run local commands for installs, debugging, and self-maintenance.</div>
                  </div>
                  <button
                    className={`toggle ${Boolean(asRecord(config.security).allow_shell_execution) ? 'on' : ''}`}
                    onClick={() => { saveSectionPatch('security', { allow_shell_execution: !Boolean(asRecord(config.security).allow_shell_execution) }); }}
                  />
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Desktop Action Delay (ms)</div>
                    <div className="settings-row-desc">Small pause between desktop actions for safer interaction on busy UIs.</div>
                  </div>
                  <input
                    className="input-field input-mono"
                    style={{ width: 120 }}
                    type="number"
                    min={0}
                    step={50}
                    defaultValue={Number(asRecord(config.desktop).action_delay_ms ?? 100)}
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
                        void clearPersistedStore().finally(() => {
                          window.location.reload();
                        });
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
