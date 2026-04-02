// NeuralClaw Desktop - Status Bar

import { useAppStore } from '../../store/appStore';
import { APP_VERSION } from '../../lib/constants';

interface Props {
  onClear: () => void;
  onResetAll: () => void;
  sessionCount: number;
}

export default function StatusBar({ onClear, onResetAll, sessionCount }: Props) {
  const { connectionStatus, backendVersion } = useAppStore();

  return (
    <div className="chat-status-bar">
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn-ghost btn-sm" onClick={onClear}>
          Clear Session
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onResetAll}>
          Reset Local Chats
        </button>
      </div>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {sessionCount} session{sessionCount === 1 ? '' : 's'}
      </span>
      <span
        style={{ fontFamily: 'var(--font-mono)' }}
        title={backendVersion ? `Gateway v${backendVersion}` : 'Gateway version unavailable'}
      >
        {`NeuralClaw Desktop v${APP_VERSION}`}
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className={`status-dot ${connectionStatus === 'connected' ? 'online' : connectionStatus === 'connecting' ? 'connecting' : 'offline'}`} />
        <span>{connectionStatus === 'connected' ? 'Connected' : connectionStatus === 'connecting' ? 'Connecting...' : 'Offline'}</span>
      </div>
    </div>
  );
}
