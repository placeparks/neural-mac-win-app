// Step 1: Welcome

import { useWizardStore } from '../store/wizardStore';

export default function Step1Welcome() {
  const { nextStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Welcome to NeuralClaw</h2>
      <p className="wizard-subtitle">
        Your personal AI assistant that lives on your computer. Private, powerful, always available.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', margin: '20px 0' }}>
        {[
          '✓ Chat with any AI model',
          '✓ Remember your conversations',
          '✓ Execute tasks and build apps',
          '✓ Connect to Telegram, Discord, and more',
          '✓ Search and learn from documents',
        ].map((item) => (
          <div
            key={item}
            style={{
              fontSize: '14px',
              color: 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span style={{ color: 'var(--accent-green)' }}>{item.slice(0, 1)}</span>
            {item.slice(2)}
          </div>
        ))}
      </div>

      <div className="wizard-footer">
        <div />
        <button className="btn btn-primary btn-lg" onClick={nextStep}>
          Get Started →
        </button>
      </div>
    </>
  );
}
