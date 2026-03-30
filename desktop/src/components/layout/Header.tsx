// NeuralClaw Desktop — Header Bar

import { useAppStore } from '../../store/appStore';

interface Props {
  title: string;
}

export default function Header({ title }: Props) {
  const { connectionStatus } = useAppStore();

  return (
    <header className="app-header">
      <h1 style={{ fontSize: 15, fontWeight: 600, flex: 1 }}>{title}</h1>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
        <span
          className={`status-dot ${
            connectionStatus === 'connected' ? 'online' :
            connectionStatus === 'connecting' ? 'connecting' : 'offline'
          }`}
        />
        {connectionStatus === 'connected' ? 'Connected' :
         connectionStatus === 'connecting' ? 'Connecting' : 'Disconnected'}
      </div>
    </header>
  );
}
