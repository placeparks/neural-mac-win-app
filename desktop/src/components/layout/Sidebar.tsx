// NeuralClaw Desktop — Sidebar Navigation

import { useAppStore } from '../../store/appStore';

interface Props {
  currentView: string;
  onNavigate: (view: string) => void;
}

const NAV_ITEMS = [
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'memory', icon: '🧠', label: 'Memory' },
  { id: 'knowledge', icon: '📚', label: 'Knowledge Base' },
  { id: 'workflows', icon: '⚡', label: 'Workflows' },
  { id: 'dashboard', icon: '📊', label: 'Dashboard' },
  { id: 'settings', icon: '⚙️', label: 'Settings' },
  { id: 'about', icon: 'ℹ️', label: 'About' },
];

export default function Sidebar({ currentView, onNavigate }: Props) {
  const { connectionStatus } = useAppStore();

  return (
    <aside className="app-sidebar">
      <div className="sidebar-logo">
        <span className="logo-icon">🧠</span>
        <span>NeuralClaw</span>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidebar-link ${currentView === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="link-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-status">
          <span
            className={`status-dot ${
              connectionStatus === 'connected' ? 'online' :
              connectionStatus === 'connecting' ? 'connecting' : 'offline'
            }`}
          />
          <span>
            {connectionStatus === 'connected' ? 'Backend Online' :
             connectionStatus === 'connecting' ? 'Connecting...' : 'Backend Offline'}
          </span>
        </div>
      </div>
    </aside>
  );
}
