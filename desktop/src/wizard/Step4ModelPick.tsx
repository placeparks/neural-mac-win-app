import { useEffect, useMemo, useState } from 'react';
import { useWizardStore } from '../store/wizardStore';
import { DEFAULT_MODELS } from '../lib/theme';
import { getProviderModels } from '../lib/api';
import { filterChatCapableModels } from '../lib/models';

const LOCAL_PROVIDERS = new Set(['local', 'meta']);
const DEFAULT_LOCAL_ENDPOINT = 'http://localhost:11434/v1';

interface ModelEntry {
  name: string;
  description: string;
  icon: string;
  provider: string;
}

export default function Step4ModelPick() {
  const {
    selectedProviders,
    selectedModel,
    setSelectedModel,
    modelRoles,
    setModelRole,
    apiEndpoints,
    nextStep,
    prevStep,
  } = useWizardStore();
  const [dynamicLocalModels, setDynamicLocalModels] = useState<ModelEntry[]>([]);
  const [localLoading, setLocalLoading] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [advancedSplit, setAdvancedSplit] = useState(false);

  const hasLocal = selectedProviders.some((provider) => LOCAL_PROVIDERS.has(provider));

  useEffect(() => {
    if (!hasLocal) {
      setDynamicLocalModels([]);
      setLocalError(null);
      return;
    }

    const localProvider = selectedProviders.find((provider) => LOCAL_PROVIDERS.has(provider)) ?? 'local';
    const endpoint =
      apiEndpoints[localProvider] ||
      apiEndpoints.local ||
      apiEndpoints.meta ||
      DEFAULT_LOCAL_ENDPOINT;

    let cancelled = false;
    setLocalLoading(true);
    setLocalError(null);

    getProviderModels(localProvider, endpoint)
      .then((models) => {
        if (cancelled) return;
        const chatModels = filterChatCapableModels(models);
        if (chatModels.length === 0) {
          setLocalError(`No chat-capable local models were found at ${endpoint}.`);
          setDynamicLocalModels([]);
          return;
        }
        setDynamicLocalModels(
          chatModels.map((model, index) => ({
            name: model.name,
            description: model.description || '',
            icon: model.icon || model.name.charAt(0).toUpperCase() || String(index + 1),
            provider: localProvider,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) {
          setLocalError(`Could not reach the local model endpoint at ${endpoint}.`);
          setDynamicLocalModels([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLocalLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [apiEndpoints, hasLocal, selectedProviders]);

  const availableModels = useMemo<ModelEntry[]>(() => [
    ...selectedProviders
      .filter((provider) => !LOCAL_PROVIDERS.has(provider))
      .flatMap((provider) => (DEFAULT_MODELS[provider] || []).map((model) => ({ ...model, provider }))),
    ...dynamicLocalModels,
  ], [dynamicLocalModels, selectedProviders]);

  const roleOptions = availableModels.map((model) => model.name);
  const fastModel = modelRoles.fast || selectedModel;
  const microModel = modelRoles.micro || selectedModel;

  const handlePrimarySelect = (model: string) => {
    setSelectedModel(model);
    setModelRole('primary', model);
    if (!advancedSplit) {
      setModelRole('fast', model);
      setModelRole('micro', model);
    }
  };

  return (
    <>
      <h2 className="wizard-title">Set your default model profile</h2>
      <p className="wizard-subtitle">
        This becomes the starting route for chat, quick tasks, and the operator flow. You can still override it later per provider, session, or database workspace.
      </p>

      <div className="wizard-inline-summary">
        <span>{availableModels.length} models available</span>
        <span>{advancedSplit ? 'Advanced split is enabled.' : 'Primary, fast, and micro will stay aligned.'}</span>
      </div>

      <div className="model-list">
        {localLoading ? (
          <div className="wizard-soft-state">Fetching local models...</div>
        ) : null}

        {!localLoading && localError ? (
          <div className="wizard-soft-error">{localError}</div>
        ) : null}

        {availableModels.map((model) => (
          <button
            key={`${model.provider}:${model.name}`}
            type="button"
            className={`model-card ${selectedModel === model.name ? 'selected' : ''}`}
            onClick={() => handlePrimarySelect(model.name)}
          >
            <span className="model-icon">{model.icon}</span>
            <div className="model-info">
              <div className="model-name">{model.name}</div>
              <div className="model-desc">{model.description || `${model.provider} route`}</div>
            </div>
            <span className="badge">{model.provider}</span>
          </button>
        ))}

        {!localLoading && availableModels.length === 0 && !localError ? (
          <div className="wizard-soft-state">No models available yet. Go back and add a provider or endpoint.</div>
        ) : null}
      </div>

      {availableModels.length > 0 ? (
        <div className="card wizard-advanced-card">
          <label className="wizard-split-toggle">
            <input
              type="checkbox"
              checked={advancedSplit}
              onChange={(event) => {
                const enabled = event.target.checked;
                setAdvancedSplit(enabled);
                if (!enabled && selectedModel) {
                  setModelRole('fast', selectedModel);
                  setModelRole('micro', selectedModel);
                }
              }}
            />
            <div>
              <div className="wizard-advanced-title">Split models by role</div>
              <div className="wizard-advanced-copy">
                Keep a stronger primary model for depth and use smaller fast or micro routes for routing, short decisions, and tool loops.
              </div>
            </div>
          </label>

          {advancedSplit ? (
            <div className="wizard-role-grid">
              <label className="wizard-role-card">
                <span>Fast role</span>
                <select className="input-field" value={fastModel} onChange={(event) => setModelRole('fast', event.target.value)}>
                  {roleOptions.map((name) => (
                    <option key={`fast-${name}`} value={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label className="wizard-role-card">
                <span>Micro role</span>
                <select className="input-field" value={microModel} onChange={(event) => setModelRole('micro', event.target.value)}>
                  {roleOptions.map((name) => (
                    <option key={`micro-${name}`} value={name}>{name}</option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>Back</button>
        <button className="btn btn-primary" onClick={nextStep} disabled={!selectedModel}>
          Continue
        </button>
      </div>
    </>
  );
}
