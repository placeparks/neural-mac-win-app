// Step 2: AI Provider Selection

import { useWizardStore } from '../store/wizardStore';
import { ALL_PROVIDERS, PROVIDER_COLORS } from '../lib/theme';

export default function Step2Providers() {
  const { selectedProviders, toggleProvider, nextStep, prevStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Which AI companies do you use?</h2>
      <p className="wizard-subtitle">Select all that apply. You can always add more later.</p>

      <div className="provider-grid">
        {ALL_PROVIDERS.map((p) => {
          const colors = PROVIDER_COLORS[p.id];
          const selected = selectedProviders.includes(p.id);
          return (
            <div
              key={p.id}
              className={`provider-card ${selected ? 'selected' : ''}`}
              onClick={() => toggleProvider(p.id)}
            >
              {selected && <div className="check-badge">✓</div>}
              <div
                className="provider-icon"
                style={{ background: colors.bg, color: colors.text }}
              >
                {colors.icon}
              </div>
              <div className="provider-name">{p.name}</div>
              <div className="provider-company">{p.company}</div>
            </div>
          );
        })}
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>
          ← Back
        </button>
        <button
          className="btn btn-primary"
          onClick={nextStep}
          disabled={selectedProviders.length === 0}
        >
          Continue →
        </button>
      </div>
    </>
  );
}
