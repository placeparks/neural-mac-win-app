import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { useWizardStore } from '../store/wizardStore';
import { PROVIDER_COLORS } from '../lib/theme';

export default function Step3ApiKey() {
  const {
    selectedProviders,
    apiKeys,
    apiEndpoints,
    setApiKey,
    setApiEndpoint,
    currentKeyProvider,
    setCurrentKeyProvider,
    nextStep,
    prevStep,
  } = useWizardStore();
  const [showKey, setShowKey] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState<boolean | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (selectedProviders.length === 0) {
      setCurrentKeyProvider(0);
      return;
    }
    if (currentKeyProvider > selectedProviders.length - 1) {
      setCurrentKeyProvider(selectedProviders.length - 1);
    }
  }, [currentKeyProvider, selectedProviders, setCurrentKeyProvider]);

  const provider = selectedProviders[currentKeyProvider];
  if (!provider) return null;

  const colors = PROVIDER_COLORS[provider];
  const key = apiKeys[provider] || '';
  const endpoint = apiEndpoints[provider] || '';
  const needsApiKey = provider !== 'local' && provider !== 'meta';

  const resetValidation = () => {
    setValidated(null);
    setErrorMsg(null);
  };

  const handleValidate = async () => {
    setValidating(true);
    setErrorMsg(null);
    try {
      const result = await invoke<string>('validate_api_key', {
        provider,
        apiKey: key,
        endpoint: endpoint || null,
      });
      const parsed = JSON.parse(result);
      setValidated(Boolean(parsed.valid));
      if (!parsed.valid) {
        setErrorMsg('The provider rejected the credentials or endpoint.');
      }
    } catch (error) {
      setValidated(false);
      setErrorMsg(error instanceof Error ? error.message : 'Validation failed. Check the key and network path.');
    } finally {
      setValidating(false);
    }
  };

  const handleContinue = () => {
    if (currentKeyProvider < selectedProviders.length - 1) {
      setCurrentKeyProvider(currentKeyProvider + 1);
      setShowKey(false);
      resetValidation();
      return;
    }
    nextStep();
  };

  const handleBack = () => {
    if (currentKeyProvider > 0) {
      setCurrentKeyProvider(currentKeyProvider - 1);
      setShowKey(false);
      resetValidation();
      return;
    }
    prevStep();
  };

  const osName = navigator.userAgent.includes('Mac')
    ? 'macOS Keychain'
    : navigator.userAgent.includes('Win')
      ? 'Windows Credential Manager'
      : 'system keyring';

  return (
    <>
      <div className="wizard-provider-header">
        <div className="provider-icon wizard-provider-icon" style={{ background: colors.bg, color: colors.text }}>
          {colors.icon}
        </div>
        <div>
          <h2 className="wizard-title">Configure {colors.label}</h2>
          <p className="wizard-subtitle">
            {needsApiKey
              ? `Store the API key and optional endpoint for ${colors.label}.`
              : `Set the endpoint for ${colors.label}. No remote API key is required.`}
          </p>
        </div>
      </div>

      <div className="wizard-inline-summary">
        <span>Provider {currentKeyProvider + 1} of {selectedProviders.length}</span>
        <span>Secrets stay local in {osName}.</span>
      </div>

      <div className="wizard-form-card">
        {needsApiKey ? (
          <div className="input-group">
            <label className="input-label">API Key</label>
            <div className="wizard-inline-field">
              <input
                className="input-field input-mono"
                type={showKey ? 'text' : 'password'}
                placeholder="sk-..."
                value={key}
                onChange={(event) => {
                  setApiKey(provider, event.target.value);
                  resetValidation();
                }}
              />
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowKey((value) => !value)}>
                {showKey ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>
        ) : null}

        <div className="input-group">
          <label className="input-label">Endpoint {needsApiKey ? '(optional)' : ''}</label>
          <input
            className="input-field input-mono"
            type="text"
            placeholder={needsApiKey ? 'https://api.example.com/v1' : 'http://localhost:11434'}
            value={endpoint}
            onChange={(event) => {
              setApiEndpoint(provider, event.target.value);
              resetValidation();
            }}
          />
        </div>
      </div>

      {validated === true ? (
        <div className="info-box" style={{ background: 'var(--accent-green-muted)', borderColor: 'rgba(63,185,80,0.3)' }}>
          <span className="info-icon">OK</span>
          <span>{needsApiKey ? 'Credential check passed.' : 'Endpoint is reachable and ready.'}</span>
        </div>
      ) : validated === false ? (
        <div className="info-box" style={{ background: 'var(--accent-red-muted)', borderColor: 'rgba(248,81,73,0.3)' }}>
          <span className="info-icon">!</span>
          <span>{errorMsg || 'Validation failed.'}</span>
        </div>
      ) : (
        <div className="info-box">
          <span className="info-icon">i</span>
          <span>Validate if you want a live check now. You can continue and change this later in Connections.</span>
        </div>
      )}

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={handleBack}>
          Back
        </button>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="btn btn-secondary"
            onClick={() => { void handleValidate(); }}
            disabled={validating || (needsApiKey && !key)}
          >
            {validating ? 'Verifying...' : 'Validate'}
          </button>
          <button className="btn btn-primary" onClick={handleContinue} disabled={needsApiKey && !key}>
            Continue
          </button>
        </div>
      </div>
    </>
  );
}
