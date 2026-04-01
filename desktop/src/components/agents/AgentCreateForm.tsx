// NeuralClaw Desktop — Agent Create/Edit Form

import { useState, useEffect } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { AgentDefinition } from '../../lib/api';
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

  const models = (DEFAULT_MODELS as Record<string, any>)[provider] || [];

  useEffect(() => {
    // Set default base URL based on provider
    if (!initial) {
      if (provider === 'local') setBaseUrl('http://localhost:11434/v1');
      else if (provider === 'openai') setBaseUrl('https://api.openai.com/v1');
      else setBaseUrl('');
    }
  }, [provider, initial]);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await invoke<string>('validate_api_key', {
        provider: provider === 'local' ? 'local' : provider,
        apiKey: apiKey || 'local',
        endpoint: baseUrl || undefined,
      });
      const parsed = JSON.parse(result);
      setTestResult(parsed.valid ? 'Connected!' : `Failed: ${parsed.error || 'Unknown'}`);
    } catch (e: any) {
      setTestResult(`Error: ${e?.message || e}`);
    }
    setTesting(false);
  };

  const handleSave = () => {
    const caps = capabilities
      .split(',')
      .map((c) => c.trim())
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
        {/* Name */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Name</label>
          <input
            className="input-field"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="research-agent"
            disabled={!!initial}
          />
        </div>

        {/* Description */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Description</label>
          <input
            className="input-field"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Specialized in web research and analysis"
          />
        </div>

        {/* System Prompt */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>System Prompt</label>
          <textarea
            className="input-field"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="You are a research assistant that..."
            rows={3}
            style={{ resize: 'vertical', minHeight: 60 }}
          />
        </div>

        {/* Provider */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Provider</label>
          <select className="input-field" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </div>

        {/* Model */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Model</label>
          {models.length > 0 ? (
            <select className="input-field" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">Select model...</option>
              {models.map((m: any) => (
                <option key={m.name} value={m.name}>
                  {m.icon} {m.name} — {m.description}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="input-field"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="model-name"
            />
          )}
        </div>

        {/* Base URL */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>Base URL</label>
          <input
            className="input-field"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="http://localhost:11434/v1"
          />
        </div>

        {/* API Key (only for non-local) */}
        {provider !== 'local' && (
          <div>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>API Key</label>
            <input
              className="input-field"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
            />
          </div>
        )}

        {/* Test Connection */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button type="button" className="btn btn-secondary" onClick={handleTest} disabled={testing} style={{ fontSize: 12 }}>
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          {testResult && (
            <span style={{
              fontSize: 12,
              color: testResult.startsWith('Connected') ? 'var(--accent-green)' : 'var(--accent-red)',
            }}>
              {testResult}
            </span>
          )}
        </div>

        {/* Capabilities */}
        <div>
          <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>
            Capabilities (comma-separated)
          </label>
          <input
            className="input-field"
            value={capabilities}
            onChange={(e) => setCapabilities(e.target.value)}
            placeholder="research, code, analysis"
          />
        </div>

        {/* Auto-start */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
          <input type="checkbox" checked={autoStart} onChange={(e) => setAutoStart(e.target.checked)} />
          <span style={{ fontSize: 13 }}>Auto-start on launch</span>
        </label>

        {/* Actions */}
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
