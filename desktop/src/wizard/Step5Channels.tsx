import { useWizardStore } from '../store/wizardStore';

const CHANNELS = [
  { id: 'telegram', name: 'Telegram', icon: 'TG', desc: 'Bot and personal assistant surface' },
  { id: 'discord', name: 'Discord', icon: 'DC', desc: 'Community or team chat operations' },
  { id: 'whatsapp', name: 'WhatsApp', icon: 'WA', desc: 'Mobile-first conversational bridge' },
  { id: 'slack', name: 'Slack', icon: 'SL', desc: 'Workspace and incident collaboration' },
];

export default function Step5Channels() {
  const { selectedChannels, toggleChannel, nextStep, prevStep } = useWizardStore();

  return (
    <>
      <h2 className="wizard-title">Connect messaging channels if they matter</h2>
      <p className="wizard-subtitle">
        This is optional. The desktop app already works as the main operator surface, so only connect channels you actually plan to use.
      </p>

      <div className="channel-grid">
        {CHANNELS.map((channel) => {
          const selected = selectedChannels.includes(channel.id);
          return (
            <button
              key={channel.id}
              type="button"
              className={`channel-card ${selected ? 'selected' : ''}`}
              onClick={() => toggleChannel(channel.id)}
            >
              <span className="channel-icon">{channel.icon}</span>
              <div>
                <div className="channel-name">{channel.name}</div>
                <div className="channel-desc">{channel.desc}</div>
              </div>
              {selected ? <span className="badge badge-blue">linked</span> : null}
            </button>
          );
        })}
      </div>

      <div className="wizard-inline-summary">
        <span>{selectedChannels.length} channels selected</span>
        <span>Channel credentials can be filled in later from Settings and Connections.</span>
      </div>

      <div style={{ marginTop: 16 }}>
        <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }} onClick={nextStep}>
          Skip for now
        </button>
      </div>

      <div className="wizard-footer">
        <button className="btn btn-ghost" onClick={prevStep}>Back</button>
        <button className="btn btn-primary" onClick={nextStep}>Continue</button>
      </div>
    </>
  );
}
