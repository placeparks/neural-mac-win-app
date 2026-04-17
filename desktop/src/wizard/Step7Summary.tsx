import { useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useWizardStore } from '../store/wizardStore';
import { useAppStore } from '../store/appStore';
import { PROVIDER_COLORS } from '../lib/theme';

export default function Step7Summary() {
  const {
    selectedProviders,
    selectedModel,
    modelRoles,
    selectedChannels,
    features,
    apiKeys,
    apiEndpoints,
    prevStep,
  } = useWizardStore();
  const { setSetupComplete, setAppView } = useAppStore();
  const [submitting, setSubmitting] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);

  const handleLaunch = async () => {
    setSubmitting(true);
    setLaunchError(null);
    try {
      const primary = selectedProviders[0];
      const providers: Record<string, unknown> = {};
      if (primary) providers.primary = primary;

      for (const provider of selectedProviders) {
        const endpoint = (apiEndpoints[provider] || '').trim();
        if (endpoint) {
          providers[provider] = { base_url: endpoint };
        }
      }

      const providerSecrets: Record<string, string> = {};
      for (const provider of selectedProviders) {
        if (provider === 'local' || provider === 'meta') continue;
        const key = (apiKeys[provider] || '').trim();
        if (key) providerSecrets[provider] = key;
      }

      const payload: Record<string, unknown> = {
        providers,
        provider_secrets: providerSecrets,
        features,
      };

      if (selectedModel) {
        const roles: Record<string, unknown> = {
          primary: modelRoles.primary || selectedModel,
          fast: modelRoles.fast || modelRoles.primary || selectedModel,
          micro: modelRoles.micro || modelRoles.primary || selectedModel,
        };
        const localEndpoint = (apiEndpoints.local || apiEndpoints.meta || '').trim();
        if (localEndpoint) roles.base_url = localEndpoint;
        payload.model_roles = roles;
      }

      await invoke('save_wizard_config', { config: payload });
      void invoke('stop_backend').catch(() => undefined);
      window.setTimeout(() => {
        void invoke('start_backend').catch(() => undefined);
      }, 500);

      setSetupComplete(true);
      setAppView('app');
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : String(error));
      setSubmitting(false);
    }
  };

  const primaryProvider = selectedProviders[0];
  const providerLabel = primaryProvider ? PROVIDER_COLORS[primaryProvider].label : 'None';

  return (
    <>
      <h2 className="wizard-title">Ready to launch the desktop runtime</h2>
      <p className="wizard-subtitle">
        This writes the config locally, restarts the backend with the new settings, and drops you into the production shell.
      </p>

      <div className="summary-grid">
        <div className="summary-row">
          <span className="summary-label">Primary Route</span>
          <span className="summary-value">{providerLabel}</span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Primary Model</span>
          <span className="summary-value wizard-mono">{modelRoles.primary || selectedModel || 'Not selected'}</span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Fast / Micro</span>
          <span className="summary-value wizard-mono">
            {(modelRoles.fast || selectedModel || 'Not selected')} / {(modelRoles.micro || selectedModel || 'Not selected')}
          </span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Channels</span>
          <span className="summary-value">{selectedChannels.length > 0 ? selectedChannels.join(', ') : 'Desktop only'}</span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Enabled Features</span>
          <span className="summary-value">
            {Object.entries(features)
              .filter(([, enabled]) => enabled)
              .map(([name]) => name.replace(/_/g, ' '))
              .join(', ')}
          </span>
        </div>
      </div>

      {launchError ? (
        <div className="info-box" style={{ background: 'var(--accent-red-muted)', borderColor: 'rgba(248,81,73,0.3)', marginTop: 12 }}>
          <span className="info-icon">!</span>
          <span>{launchError}</span>
        </div>
      ) : (
        <div className="info-box" style={{ marginTop: 12 }}>
          <span className="info-icon">i</span>
          <span>The first runtime boot can take longer than later launches while the packaged backend fully initializes.</span>
        </div>
      )}

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep} disabled={submitting}>Back</button>
        <button className="btn btn-success btn-lg" onClick={() => { void handleLaunch(); }} disabled={submitting}>
          {submitting ? 'Launching...' : 'Launch NeuralClaw'}
        </button>
      </div>
    </>
  );
}
