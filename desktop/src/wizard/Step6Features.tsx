import { useWizardStore } from '../store/wizardStore';

const FEATURES = [
  { id: 'memory', name: 'Memory', icon: 'MM', desc: 'Conversation and preference continuity' },
  { id: 'knowledge_base', name: 'Knowledge Base', icon: 'KB', desc: 'Indexed docs and grounded retrieval' },
  { id: 'workflows', name: 'Workflows', icon: 'WF', desc: 'Multi-step execution paths and routines' },
  { id: 'dashboard', name: 'Dashboard', icon: 'OP', desc: 'Operator brief, audit, and trust rails' },
  { id: 'biometric_lock', name: 'Biometric Lock', icon: 'ID', desc: 'Protect local access on shared machines' },
];

export default function Step6Features() {
  const { features, toggleFeature, nextStep, prevStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Enable the premium product slices</h2>
      <p className="wizard-subtitle">
        These switches decide how much NeuralClaw exposes on day one. They are safe to change later, but this is the cleanest time to shape the default experience.
      </p>

      <div className="feature-list">
        {FEATURES.map((feature) => (
          <div key={feature.id} className="feature-row">
            <div className="feature-info">
              <span className="feature-icon">{feature.icon}</span>
              <div>
                <div className="feature-name">{feature.name}</div>
                <div className="feature-desc">{feature.desc}</div>
              </div>
            </div>
            <button
              className={`toggle ${features[feature.id] ? 'on' : ''}`}
              onClick={() => toggleFeature(feature.id)}
              aria-label={`Toggle ${feature.name}`}
            />
          </div>
        ))}
      </div>

      <div className="wizard-inline-summary">
        <span>{Object.values(features).filter(Boolean).length} enabled</span>
        <span>Dashboard, memory, and knowledge usually produce the best first impression.</span>
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>Back</button>
        <button className="btn btn-primary" onClick={nextStep}>Continue</button>
      </div>
    </>
  );
}
