// NeuralClaw Desktop - Agent Create/Edit Form

import { useEffect, useMemo, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import {
  AgentDefinition,
  getPrimaryProviderDefaults,
  getProviderDefaults,
  getProviderModels,
  type ModelOption,
} from '../../lib/api';
import { DEFAULT_MODELS } from '../../lib/theme';

interface Props {
  initial?: AgentDefinition | null;
  saving?: boolean;
  error?: string | null;
  onSave: (data: Partial<AgentDefinition>) => void;
  onCancel: () => void;
}

const PROVIDERS = [
  { id: 'local', label: 'Ollama (Local)' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'google', label: 'Google' },
  { id: 'xai', label: 'xAI (Grok)' },
  { id: 'openrouter', label: 'OpenRouter' },
  { id: 'mistral', label: 'Mistral' },
  { id: 'venice', label: 'Venice' },
];

function fallbackBaseUrl(provider: string) {
  if (provider === 'local' || provider === 'meta') return 'http://localhost:11434/v1';
  if (provider === 'openai') return 'https://api.openai.com/v1';
  if (provider === 'anthropic') return 'https://api.anthropic.com';
  if (provider === 'google') return 'https://generativelanguage.googleapis.com/v1beta';
  if (provider === 'openrouter') return 'https://openrouter.ai/api/v1';
  if (provider === 'mistral') return 'https://api.mistral.ai/v1';
  if (provider === 'venice') return 'https://api.venice.ai/api/v1';
  if (provider === 'xai') return 'https://api.x.ai/v1';
  return '';
}

export default function AgentCreateForm({ initial, saving = false, error = null, onSave, onCancel }: Props) {
  const [name, setName] = useState(initial?.name || '');
  const [description, setDescription] = useState(initial?.description || '');
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt || '');
  const [provider, setProvider] = useState(initial?.provider || 'local');
  const [model, setModel] = useState(initial?.model || '');
  const [baseUrl, setBaseUrl] = useState(initial?.base_url || '');
  const [apiKey, setApiKey] = useState('');
  const [capabilities, setCapabilities] = useState(initial?.capabilities?.join(', ') || '');
  const [autoStart, setAutoStart] = useState(initial?.auto_start || false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [remoteModels, setRemoteModels] = useState<ModelOption[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  const fallbackModels = useMemo(
    () => (DEFAULT_MODELS as Record<string, ModelOption[]>)[provider] || [],
    [provider],
  );
  const models = remoteModels.length ? remoteModels : fallbackModels;

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    void getPrimaryProviderDefaults()
      .then((defaults) => {
        if (cancelled) return;
        const nextProvider = PROVIDERS.some((entry) => entry.id === defaults.provider) ? defaults.provider : 'local';
        setProvider(nextProvider);
        setBaseUrl(defaults.baseUrl || fallbackBaseUrl(nextProvider));
        if (defaults.model.trim()) setModel(defaults.model.trim());
      })
      .catch(() => {
        if (!cancelled) setBaseUrl(fallbackBaseUrl('local'));
      });
    return () => {
      cancelled = true;
    };
  }, [initial]);

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    void getProviderDefaults(provider)
      .then((defaults) => {
        if (cancelled) return;
        setBaseUrl(defaults.baseUrl || fallbackBaseUrl(provider));
        if (!model.trim() && defaults.model.trim()) {
          setModel(defaults.model.trim());
        }
      })
      .catch(() => {
        if (!cancelled) setBaseUrl(fallbackBaseUrl(provider));
      });
    return () => {
      cancelled = true;
    };
  }, [initial, provider]);

  useEffect(() => {
    let cancelled = false;
    const endpoint = baseUrl || fallbackBaseUrl(provider);
    setLoadingModels(true);
    getProviderModels(provider, endpoint, apiKey || undefined)
      .then((items) => {
        if (!cancelled) setRemoteModels(items);
      })
      .catch(() => {
        if (!cancelled) setRemoteModels([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });

    return () => {
      cancelled = true;
    };
  }, [apiKey, baseUrl, provider]);

  useEffect(() => {
    if (!models.length) return;
    const hasCurrentModel = models.some((entry) => entry.name === model);
    if (!model.trim() || !hasCurrentModel) {
      setModel(models[0].name);
    }
  }, [model, models]);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await invoke<string>('validate_api_key', {
        provider: provider === 'local' ? 'local' : provider,
        apiKey: apiKey || 'local',
        endpoint: baseUrl || undefined,
      });
      const parsed = JSON.parse(result) as { valid?: boolean; error?: string };
      setTestResult(parsed.valid ? 'Connected' : `Failed: ${parsed.error || 'Unknown error'}`);
    } catch (e: any) {
      setTestResult(`Error: ${e?.message || e}`);
    }
    setTesting(false);
  };

  const handleSave = () => {
    const caps = capabilities
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean);

    const payload: Partial<AgentDefinition> = {
      name,
      description,
      system_prompt: systemPrompt,
      provider,
      model,
      base_url: baseUrl,
      capabilities: caps,
      auto_start: autoStart,
    };

    if (apiKey.trim()) {
      payload.api_key = apiKey;
    }

    onSave(payload);
  };

  return (
    <div className="card" style={{ padding: 20 }}>
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>
        {initial ? `Edit Agent: ${initial.name}` : 'Create New Agent'}
      </h3>

      {error && (
        <div
          className="info-box"
          style={{
            marginBottom: 16,
            background: 'var(--accent-red-muted)',
            borderColor: 'rgba(248,81,73,0.35)',
          }}
        >
          <span className="info-icon">!</span>
          <span>{error}</span>
        </div>
      )}

      <form
        style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
        onSubmit={(event) => {
          event.preventDefault();
          if (!saving && name.trim() && model.trim()) {
            handleSave();
          }
        }}
      >
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Name</label>
          <input
            className="input-field"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="research-agent"
            disabled={!!initial}
          />
        </div>

        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Description</label>
          <input
            className="input-field"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Specialized in research, planning, or execution"
          />
        </div>

        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>System Prompt</label>
          <textarea
            className="input-field"
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
            placeholder="You are a specialist assistant that..."
            rows={3}
            style={{ resize: 'vertical', minHeight: 60 }}
          />
        </div>

        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Provider</label>
          <select
            className="input-field"
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value);
              setRemoteModels([]);
              setTestResult(null);
              setModel('');
            }}
          >
            {PROVIDERS.map((entry) => (
              <option key={entry.id} value={entry.id}>{entry.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Model</label>
          {models.length > 0 ? (
            <select className="input-field" value={model} onChange={(event) => setModel(event.target.value)}>
              {models.map((entry) => (
                <option key={entry.name} value={entry.name}>
                  {entry.icon} {entry.name} - {entry.description}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="input-field"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="model-name"
            />
          )}
          <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-muted)' }}>
            {loadingModels ? 'Refreshing available models...' : 'Live provider models are used when available.'}
          </div>
        </div>

        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Base URL</label>
          <input
            className="input-field"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder={fallbackBaseUrl(provider)}
          />
        </div>

        {provider !== 'local' && (
          <div>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>API Key</label>
            <input
              className="input-field"
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="sk-..."
            />
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button type="button" className="btn btn-secondary" onClick={() => { void handleTest(); }} disabled={testing}>
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          {testResult && (
            <span
              style={{
                fontSize: 12,
                color: testResult === 'Connected' ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            >
              {testResult}
            </span>
          )}
        </div>

        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
            Capabilities (comma-separated)
          </label>
          <input
            className="input-field"
            value={capabilities}
            onChange={(event) => setCapabilities(event.target.value)}
            placeholder="research, analysis, planning"
          />
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
          <input type="checkbox" checked={autoStart} onChange={(event) => setAutoStart(event.target.checked)} />
          <span style={{ fontSize: 13 }}>Auto-start on launch</span>
        </label>

        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!name.trim() || !model.trim() || saving}
          >
            {saving ? (initial ? 'Updating...' : 'Creating...') : (initial ? 'Update Agent' : 'Create Agent')}
          </button>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
