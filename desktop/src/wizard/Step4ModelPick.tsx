// Step 4: Default Model Selection

import { useWizardStore } from '../store/wizardStore';
import { DEFAULT_MODELS } from '../lib/theme';

export default function Step4ModelPick() {
  const { selectedProviders, selectedModel, setSelectedModel, nextStep, prevStep } = useWizardStore();

  // Collect all models from selected providers
  const availableModels = selectedProviders.flatMap((p) =>
    (DEFAULT_MODELS[p] || []).map((m) => ({ ...m, provider: p }))
  );

  return (
    <>
      <h2 className="wizard-title">Choose your default AI model</h2>
      <p className="wizard-subtitle">You can change this anytime in Settings.</p>

      <div className="model-list">
        {availableModels.map((model) => (
          <div
            key={model.name}
            className={`model-card ${selectedModel === model.name ? 'selected' : ''}`}
            onClick={() => setSelectedModel(model.name)}
          >
            <span className="model-icon">{model.icon}</span>
            <div className="model-info">
              <div className="model-name">{model.name}</div>
              <div className="model-desc">{model.description}</div>
            </div>
            {selectedModel === model.name && (
              <span style={{ color: 'var(--accent-blue)', fontSize: 18 }}>✓</span>
            )}
          </div>
        ))}
        {availableModels.length === 0 && (
          <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 20 }}>
            No models available. Go back and select a provider.
          </p>
        )}
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>← Back</button>
        <button
          className="btn btn-primary"
          onClick={nextStep}
          disabled={!selectedModel}
        >
          Continue →
        </button>
      </div>
    </>
  );
}
