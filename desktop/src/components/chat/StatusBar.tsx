// NeuralClaw Desktop — Status Bar

import { useAppStore } from '../../store/appStore';

interface Props {
  onClear: () => void;
}

export default function StatusBar({ onClear }: Props) {
  const { connectionStatus, backendVersion } = useAppStore();

  return (
    <div className="chat-status-bar">
      <button className="btn btn-ghost btn-sm" onClick={onClear}>
        🗑 Clear
      </button>
      <span style={{ fontFamily: 'var(--font-mono)' }}>
        {backendVersion ? `NeuralClaw v${backendVersion}` : 'NeuralClaw'}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className={`status-dot ${connectionStatus === 'connected' ? 'online' : connectionStatus === 'connecting' ? 'connecting' : 'offline'}`} />
        <span>{connectionStatus === 'connected' ? 'Connected' : connectionStatus === 'connecting' ? 'Connecting...' : 'Offline'}</span>
      </div>
    </div>
  );
}
