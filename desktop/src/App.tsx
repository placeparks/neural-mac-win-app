// NeuralClaw Desktop — Main App Component

import { useState } from 'react';
import { useAppStore } from './store/appStore';
import { useHealth } from './hooks/useHealth';
import { useBackend } from './hooks/useBackend';
import Sidebar from './components/layout/Sidebar';
import WizardShell from './wizard/WizardShell';
import LockView from './views/LockView';
import ChatPage from './views/ChatPage';
import SettingsPage from './views/SettingsPage';
import MemoryPage from './views/MemoryPage';
import KnowledgePage from './views/KnowledgePage';
import WorkflowPage from './views/WorkflowPage';
import DashboardPage from './views/DashboardPage';
import AboutPage from './views/AboutPage';

export default function App() {
  const { setupComplete, isLocked, biometricEnabled } = useAppStore();
  const [currentView, setCurrentView] = useState('chat');

  // Start health polling & WebSocket connection
  useHealth();
  useBackend();

  // Show lock screen if biometrics enabled and locked
  if (biometricEnabled && isLocked) {
    return <LockView />;
  }

  // Show wizard if setup not complete
  if (!setupComplete) {
    return <WizardShell />;
  }

  // Main app layout
  const renderView = () => {
    switch (currentView) {
      case 'chat': return <ChatPage />;
      case 'settings': return <SettingsPage />;
      case 'memory': return <MemoryPage />;
      case 'knowledge': return <KnowledgePage />;
      case 'workflows': return <WorkflowPage />;
      case 'dashboard': return <DashboardPage />;
      case 'about': return <AboutPage />;
      default: return <ChatPage />;
    }
  };

  return (
    <div className="app-layout">
      <Sidebar currentView={currentView} onNavigate={setCurrentView} />
      <main className="app-main">
        {renderView()}
      </main>
    </div>
  );
}
