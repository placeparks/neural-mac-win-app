import { useAppStore } from '../../store/appStore';
import { useAgentStore } from '../../store/agentStore';
import { useTaskStore } from '../../store/taskStore';

interface Props {
  currentView: string;
  onNavigate: (view: string) => void;
}

const NAV_ITEMS = [
  { id: 'chat', icon: 'CH', label: 'Chat' },
  { id: 'tasks', icon: 'TK', label: 'Tasks' },
  { id: 'memory', icon: 'MM', label: 'Memory' },
  { id: 'knowledge', icon: 'KB', label: 'Knowledge Base' },
  { id: 'workflows', icon: 'WF', label: 'Workflows' },
  { id: 'agents', icon: 'AG', label: 'Agents' },
  { id: 'dashboard', icon: 'DB', label: 'Dashboard' },
  { id: 'settings', icon: 'CF', label: 'Settings' },
  { id: 'about', icon: 'IN', label: 'About' },
];

export default function Sidebar({ currentView, onNavigate }: Props) {
  const { connectionStatus } = useAppStore();
  const runningAgents = useAgentStore((state) => state.running.length);
  const tasks = useTaskStore((state) => state.tasks);
  const activeTasks = tasks.filter((task) => task.status === 'queued' || task.status === 'running').length;

  return (
    <aside className="app-sidebar">
      <div className="sidebar-logo">
        <span className="logo-icon">NC</span>
        <span>NeuralClaw</span>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidebar-link ${currentView === item.id ? 'active' : ''}`}
            onClick={() => onNavigate(item.id)}
            type="button"
          >
            <span className="link-icon">{item.icon}</span>
            <span className="link-label">{item.label}</span>
            {item.id === 'tasks' && activeTasks > 0 && <span className="sidebar-pill">{activeTasks}</span>}
            {item.id === 'agents' && runningAgents > 0 && <span className="sidebar-pill">{runningAgents}</span>}
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
