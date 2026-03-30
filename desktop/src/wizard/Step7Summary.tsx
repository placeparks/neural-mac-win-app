// Step 7: Summary + Launch

import { useWizardStore } from '../store/wizardStore';
import { useAppStore } from '../store/appStore';
import { PROVIDER_COLORS } from '../lib/theme';

export default function Step7Summary() {
  const {
    selectedProviders, selectedModel, selectedChannels, features, prevStep,
  } = useWizardStore();
  const { setSetupComplete, setAppView } = useAppStore();

  const handleLaunch = () => {
    setSetupComplete(true);
    setAppView('app');
  };

  const primaryProvider = selectedProviders[0];
  const providerLabel = primaryProvider ? PROVIDER_COLORS[primaryProvider].label : 'None';

  return (
    <>
      <h2 className="wizard-title">You're all set! 🎉</h2>
      <p className="wizard-subtitle">Here's a summary of your configuration.</p>

      <div className="summary-grid">
        <div className="summary-row">
          <span className="summary-label">Provider</span>
          <span className="summary-value">{providerLabel}</span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Model</span>
          <span className="summary-value" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            {selectedModel || 'Not selected'}
          </span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Channels</span>
          <span className="summary-value">
            {selectedChannels.length > 0 ? selectedChannels.join(', ') : 'None'}
          </span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Memory</span>
          <span className="summary-value">{features.memory ? 'Enabled' : 'Disabled'}</span>
        </div>
        <div className="summary-row">
          <span className="summary-label">KB</span>
          <span className="summary-value">{features.knowledge_base ? 'Enabled' : 'Disabled'}</span>
        </div>
        <div className="summary-row">
          <span className="summary-label">Lock</span>
          <span className="summary-value">{features.biometric_lock ? 'Biometric' : 'Disabled'}</span>
        </div>
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>← Back</button>
        <button className="btn btn-success btn-lg" onClick={handleLaunch}>
          🚀 Launch NeuralClaw
        </button>
      </div>

      <p style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', marginTop: 16 }}>
        You can change any of these later in Settings.
      </p>
    </>
  );
}
