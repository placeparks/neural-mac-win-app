import { useWizardStore } from '../store/wizardStore';
import { ALL_PROVIDERS, PROVIDER_COLORS } from '../lib/theme';

export default function Step2Providers() {
  const { selectedProviders, toggleProvider, nextStep, prevStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Choose your AI routes</h2>
      <p className="wizard-subtitle">
        Pick every provider you want available in the desktop shell. NeuralClaw will use this to shape chat routing, DB analysis, and operator recommendations.
      </p>

      <div className="provider-grid">
        {ALL_PROVIDERS.map((provider) => {
          const colors = PROVIDER_COLORS[provider.id];
          const selected = selectedProviders.includes(provider.id);
          return (
            <button
              key={provider.id}
              type="button"
              className={`provider-card ${selected ? 'selected' : ''}`}
              onClick={() => toggleProvider(provider.id)}
            >
              {selected && <div className="check-badge">OK</div>}
              <div className="provider-icon" style={{ background: colors.bg, color: colors.text }}>
                {colors.icon}
              </div>
              <div className="provider-name">{provider.name}</div>
              <div className="provider-company">{provider.company}</div>
            </button>
          );
        })}
      </div>

      <div className="wizard-inline-summary">
        <span>{selectedProviders.length} provider{selectedProviders.length === 1 ? '' : 's'} selected</span>
        <span>{selectedProviders.length > 0 ? 'You can still add or remove them later in Connections.' : 'Select at least one provider to continue.'}</span>
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>
          Back
        </button>
        <button
          className="btn btn-primary"
          onClick={nextStep}
          disabled={selectedProviders.length === 0}
        >
          Continue
        </button>
      </div>
    </>
  );
}
