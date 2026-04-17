import type { ReactNode } from 'react';
import { useAppStore } from '../../store/appStore';
import { useAgentStore } from '../../store/agentStore';
import { useTaskStore } from '../../store/taskStore';

interface Props {
  currentView: string;
  onNavigate: (view: string) => void;
}

// Inline SVG icons — no external dependency needed
const ICONS: Record<string, ReactNode> = {
  chat: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  ),
  tasks: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  ),
  memory: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4z" />
      <circle cx="12" cy="15" r="2" />
    </svg>
  ),
  knowledge: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  ),
  workflows: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="5" r="3" /><line x1="12" y1="8" x2="12" y2="16" /><circle cx="12" cy="19" r="3" />
      <line x1="6" y1="12" x2="18" y2="12" /><circle cx="5" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
    </svg>
  ),
  agents: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  ),
  database: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  ),
  workspace: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  ),
  dashboard: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  ),
  connections: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 12h8" /><path d="M12 8v8" />
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <rect x="14" y="14" width="7" height="7" rx="2" />
    </svg>
  ),
  settings: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
  about: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
};

interface NavSection {
  label: string;
  items: { id: string; label: string }[];
}

const SECTIONS: NavSection[] = [
  {
    label: 'Core',
    items: [
      { id: 'chat', label: 'Chat' },
      { id: 'tasks', label: 'Tasks' },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { id: 'memory', label: 'Memory' },
      { id: 'knowledge', label: 'Knowledge Base' },
      { id: 'database', label: 'Database BI' },
      { id: 'workspace', label: 'Workspace' },
      { id: 'workflows', label: 'Workflows' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { id: 'agents', label: 'Agents' },
      { id: 'connections', label: 'Connections' },
      { id: 'dashboard', label: 'Dashboard' },
    ],
  },
  {
    label: '',
    items: [
      { id: 'settings', label: 'Settings' },
      { id: 'about', label: 'About' },
    ],
  },
];

export default function Sidebar({ currentView, onNavigate }: Props) {
  const { connectionStatus, realtimeStatus, backendVersion } = useAppStore();
  const runningAgents = useAgentStore((state) => state.running.length);
  const tasks = useTaskStore((state) => state.tasks);
  const activeTasks = tasks.filter((task) => task.status === 'queued' || task.status === 'running').length;
  const shellStatus = connectionStatus === 'connected'
    ? 'Backend online'
    : connectionStatus === 'connecting'
      ? 'Booting runtime'
      : 'Backend offline';
  const syncStatus = connectionStatus === 'connected'
    ? (realtimeStatus === 'connecting' ? 'Live sync is reattaching' : 'Live sync steady')
    : 'Waiting for runtime contract';

  return (
    <aside className="app-sidebar">
      <div className="sidebar-logo">
        <span className="logo-icon">NC</span>
        <div className="sidebar-logo-copy">
          <span>NeuralClaw</span>
          <span className="sidebar-logo-meta">{backendVersion ? `Runtime v${backendVersion}` : 'Adaptive desktop shell'}</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {SECTIONS.map((section, sectionIndex) => (
          <div key={sectionIndex} className="sidebar-section">
            {section.label && (
              <div className="sidebar-section-label">{section.label}</div>
            )}
            <div className="sidebar-section-card">
              {section.items.map((item) => (
                <button
                  key={item.id}
                  className={`sidebar-link ${currentView === item.id ? 'active' : ''}`}
                  onClick={() => onNavigate(item.id)}
                  type="button"
                  title={item.label}
                >
                  <span className="link-icon">{ICONS[item.id]}</span>
                  <span className="link-label">{item.label}</span>
                  {item.id === 'tasks' && activeTasks > 0 && <span className="sidebar-pill">{activeTasks}</span>}
                  {item.id === 'agents' && runningAgents > 0 && <span className="sidebar-pill">{runningAgents}</span>}
                </button>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className={`sidebar-status is-${connectionStatus}`}>
          <div className="sidebar-status-head">
            <span
              className={`status-dot ${
                connectionStatus === 'connected' ? 'online' :
                connectionStatus === 'connecting' ? 'connecting' : 'offline'
              }`}
            />
            <span>{shellStatus}</span>
          </div>
          <div className="sidebar-status-subtle">{syncStatus}</div>
        </div>
      </div>
    </aside>
  );
}
