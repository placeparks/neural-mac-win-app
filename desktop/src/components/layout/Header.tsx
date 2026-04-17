// NeuralClaw Desktop — Header Bar

import { useAppStore } from '../../store/appStore';

interface Props {
  title: string;
  subtitle?: string;
}

export default function Header({ title, subtitle }: Props) {
  const { connectionStatus, realtimeStatus } = useAppStore();

  const statusLabel = connectionStatus === 'connected'
    ? (realtimeStatus === 'connecting' ? 'Online · Syncing live feed' : 'Online')
    : connectionStatus === 'connecting'
      ? 'Starting'
      : 'Offline';

  return (
    <header className="app-header">
      <div className="app-header-copy">
        <div className="app-header-eyebrow">Neural Workspace</div>
        <h1 className="app-header-title">{title}</h1>
        {subtitle && <p className="app-header-subtitle">{subtitle}</p>}
      </div>
      <div className={`app-header-status is-${connectionStatus}`}>
        <span
          className={`status-dot ${
            connectionStatus === 'connected' ? 'online' :
            connectionStatus === 'connecting' ? 'connecting' : 'offline'
          }`}
        />
        <span>{statusLabel}</span>
      </div>
    </header>
  );
}
