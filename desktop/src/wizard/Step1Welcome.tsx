import { useWizardStore } from '../store/wizardStore';

const WELCOME_POINTS = [
  'Run local-first chat, tasks, and agent workflows from one shell.',
  'Persist memory, knowledge, connections, and DB workspaces for the user.',
  'Control model routes explicitly instead of accepting hidden fallback behavior.',
  'Use audit trails, operator surfaces, and runtime health that match reality.',
];

export default function Step1Welcome() {
  const { nextStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">A desktop agent surface that feels deliberate</h2>
      <p className="wizard-subtitle">
        This setup flow configures the runtime contract, provider routes, and premium product slices so the app feels stable from the first launch.
      </p>

      <div className="wizard-hero-grid">
        <div className="wizard-signal-card">
          <div className="eyebrow">What You Get</div>
          <div className="wizard-bullet-list">
            {WELCOME_POINTS.map((item) => (
              <div key={item} className="wizard-bullet-row">
                <span className="wizard-bullet-dot" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="wizard-mini-metrics">
          <div className="wizard-mini-metric">
            <span>Runtime</span>
            <strong>Desktop + sidecar</strong>
          </div>
          <div className="wizard-mini-metric">
            <span>Persistence</span>
            <strong>User-owned state</strong>
          </div>
          <div className="wizard-mini-metric">
            <span>Mode</span>
            <strong>Local-first premium</strong>
          </div>
        </div>
      </div>

      <div className="wizard-footer">
        <div className="wizard-footer-note">Takes about a minute if you already know your provider and preferred model.</div>
        <button className="btn btn-primary btn-lg" onClick={nextStep}>
          Start Setup
        </button>
      </div>
    </>
  );
}
