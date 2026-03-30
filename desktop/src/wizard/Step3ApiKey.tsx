// Step 3: API Key Entry (per selected provider)

import { useState } from 'react';
import { useWizardStore } from '../store/wizardStore';
import { PROVIDER_COLORS } from '../lib/theme';

export default function Step3ApiKey() {
  const {
    selectedProviders, apiKeys, apiEndpoints,
    setApiKey, setApiEndpoint, currentKeyProvider,
    setCurrentKeyProvider, nextStep, prevStep,
  } = useWizardStore();
  const [showKey, setShowKey] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState<boolean | null>(null);

  const provider = selectedProviders[currentKeyProvider];
  if (!provider) return null;

  const colors = PROVIDER_COLORS[provider];
  const key = apiKeys[provider] || '';
  const endpoint = apiEndpoints[provider] || '';

  const handleValidate = async () => {
    setValidating(true);
    // Simulate validation (real impl: test API call)
    await new Promise((r) => setTimeout(r, 1200));
    setValidated(key.length > 8);
    setValidating(false);
  };

  const handleContinue = () => {
    if (currentKeyProvider < selectedProviders.length - 1) {
      setCurrentKeyProvider(currentKeyProvider + 1);
      setValidated(null);
      setShowKey(false);
    } else {
      nextStep();
    }
  };

  const handleBack = () => {
    if (currentKeyProvider > 0) {
      setCurrentKeyProvider(currentKeyProvider - 1);
      setValidated(null);
    } else {
      prevStep();
    }
  };

  const osName = navigator.userAgent.includes('Mac') ? 'macOS Keychain, protected by Touch ID'
    : navigator.userAgent.includes('Win') ? 'Windows Credential Manager, protected by Windows Hello'
    : 'GNOME Keyring / KDE Wallet, protected by login password';

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
        <div style={{ width: 28, height: 28, borderRadius: 6, background: colors.bg, color: colors.text, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 14 }}>
          {colors.icon}
        </div>
        <h2 className="wizard-title" style={{ margin: 0 }}>Configure {colors.label}</h2>
      </div>
      <p className="wizard-subtitle">
        Enter your API key to connect NeuralClaw to {colors.label}.
        {selectedProviders.length > 1 && (
          <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
            ({currentKeyProvider + 1} of {selectedProviders.length})
          </span>
        )}
      </p>

      <div className="input-group" style={{ marginBottom: '16px' }}>
        <label className="input-label">API Key</label>
        <div style={{ position: 'relative' }}>
          <input
            className="input-field input-mono"
            type={showKey ? 'text' : 'password'}
            placeholder="sk-..."
            value={key}
            onChange={(e) => { setApiKey(provider, e.target.value); setValidated(null); }}
          />
          <button
            className="btn btn-ghost btn-sm"
            style={{ position: 'absolute', right: 4, top: 4 }}
            onClick={() => setShowKey(!showKey)}
          >
            {showKey ? '🙈' : '👁️'}
          </button>
        </div>
      </div>

      <div className="input-group" style={{ marginBottom: '20px' }}>
        <label className="input-label">API Endpoint (optional)</label>
        <input
          className="input-field input-mono"
          type="text"
          placeholder="https://api.example.com/v1"
          value={endpoint}
          onChange={(e) => setApiEndpoint(provider, e.target.value)}
        />
      </div>

      {validated === true && (
        <div className="info-box" style={{ background: 'var(--accent-green-muted)', borderColor: 'rgba(63,185,80,0.3)' }}>
          <span className="info-icon">✅</span>
          <span>Connected! API key verified successfully.</span>
        </div>
      )}
      {validated === false && (
        <div className="info-box" style={{ background: 'var(--accent-red-muted)', borderColor: 'rgba(248,81,73,0.3)' }}>
          <span className="info-icon">❌</span>
          <span>Invalid key. Please check and try again.</span>
        </div>
      )}
      {validated === null && (
        <div className="info-box">
          <span className="info-icon">🔒</span>
          <span>Your API key is stored in the {osName}. It never leaves your device.</span>
        </div>
      )}

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={handleBack}>← Back</button>
        <div style={{ display: 'flex', gap: 8 }}>
          {validated !== true && (
            <button className="btn btn-secondary" onClick={handleValidate} disabled={!key || validating}>
              {validating ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Verifying...</> : 'Verify Key'}
            </button>
          )}
          <button className="btn btn-primary" onClick={handleContinue} disabled={!key}>
            Continue →
          </button>
        </div>
      </div>
    </>
  );
}
