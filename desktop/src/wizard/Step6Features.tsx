// Step 6: Feature Toggles

import { useWizardStore } from '../store/wizardStore';

const FEATURES = [
  { id: 'memory', name: 'Memory', icon: '🧠', desc: 'Remember conversations', default: true },
  { id: 'knowledge_base', name: 'Knowledge Base', icon: '📚', desc: 'Search your documents', default: true },
  { id: 'workflows', name: 'Workflows', icon: '⚡', desc: 'Multi-step task automation', default: false },
  { id: 'dashboard', name: 'Dashboard', icon: '🌐', desc: 'Web monitoring panel', default: true },
  { id: 'biometric_lock', name: 'Biometric Lock', icon: '🔒', desc: 'Require auth to access', default: true },
];

export default function Step6Features() {
  const { features, toggleFeature, nextStep, prevStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Customize your experience</h2>
      <p className="wizard-subtitle">Toggle features on or off. You can change these anytime.</p>

      <div className="feature-list">
        {FEATURES.map((feat) => (
          <div key={feat.id} className="feature-row">
            <div className="feature-info">
              <span className="feature-icon">{feat.icon}</span>
              <div>
                <div className="feature-name">{feat.name}</div>
                <div className="feature-desc">{feat.desc}</div>
              </div>
            </div>
            <button
              className={`toggle ${features[feat.id] ? 'on' : ''}`}
              onClick={() => toggleFeature(feat.id)}
              aria-label={`Toggle ${feat.name}`}
            />
          </div>
        ))}
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>← Back</button>
        <button className="btn btn-primary" onClick={nextStep}>
          Continue →
        </button>
      </div>
    </>
  );
}
