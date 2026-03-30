// Step 5: Channel Configuration

import { useWizardStore } from '../store/wizardStore';

const CHANNELS = [
  { id: 'telegram', name: 'Telegram', icon: '✈️', desc: 'Bot via @BotFather' },
  { id: 'discord', name: 'Discord', icon: '💬', desc: 'Discord Bot' },
  { id: 'whatsapp', name: 'WhatsApp', icon: '📱', desc: 'WhatsApp Bridge' },
  { id: 'slack', name: 'Slack', icon: '💼', desc: 'Slack Bot' },
];

export default function Step5Channels() {
  const { selectedChannels, toggleChannel, nextStep, prevStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Connect your messaging apps</h2>
      <p className="wizard-subtitle">
        Optional — you can always chat here in the desktop app. Configure channels later in Settings.
      </p>

      <div className="channel-grid">
        {CHANNELS.map((ch) => {
          const selected = selectedChannels.includes(ch.id);
          return (
            <div
              key={ch.id}
              className={`channel-card ${selected ? 'selected' : ''}`}
              onClick={() => toggleChannel(ch.id)}
            >
              <span className="channel-icon">{ch.icon}</span>
              <div>
                <div className="channel-name">{ch.name}</div>
                <div className="channel-desc">{ch.desc}</div>
              </div>
              {selected && (
                <span style={{ marginLeft: 'auto', color: 'var(--accent-blue)' }}>✓</span>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 16 }}>
        <button
          className="btn btn-ghost"
          style={{ width: '100%', justifyContent: 'center' }}
          onClick={nextStep}
        >
          ⏭️ Skip for now
        </button>
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
