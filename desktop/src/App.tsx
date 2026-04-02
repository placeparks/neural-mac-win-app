// NeuralClaw Desktop - Main App Component

import { Suspense, lazy, useEffect, useState } from 'react';
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';
import { useAppStore } from './store/appStore';
import { useHealth } from './hooks/useHealth';
import { useBackend } from './hooks/useBackend';
import Sidebar from './components/layout/Sidebar';
import ToastViewport from './components/layout/ToastViewport';
import WizardShell from './wizard/WizardShell';
import LockView from './views/LockView';
import ChatPage from './views/ChatPage';
import SettingsPage from './views/SettingsPage';
import MemoryPage from './views/MemoryPage';
import KnowledgePage from './views/KnowledgePage';
import TasksPage from './views/TasksPage';
import WorkflowPage from './views/WorkflowPage';
import DashboardPage from './views/DashboardPage';
import AboutPage from './views/AboutPage';

const AgentsPage = lazy(() => import('./views/AgentsPage'));
const AvatarWindow = lazy(() => import('./avatar/AvatarWindow'));

const currentWindow = getCurrentWebviewWindow();
const isAvatarWindow = currentWindow.label === 'avatar' || window.location.pathname === '/avatar';

export default function App() {
  const { setupComplete, isLocked, biometricEnabled } = useAppStore();
  const [currentView, setCurrentView] = useState(() => localStorage.getItem('neuralclaw_current_view') || 'chat');

  useHealth();
  useBackend();

  useEffect(() => {
    if (isAvatarWindow) return;
    const handleNavigate = (event: Event) => {
      const nextView = (event as CustomEvent<string>).detail || 'chat';
      setCurrentView(nextView);
    };
    window.addEventListener('neuralclaw:navigate', handleNavigate as EventListener);
    return () => window.removeEventListener('neuralclaw:navigate', handleNavigate as EventListener);
  }, []);

  useEffect(() => {
    if (!isAvatarWindow) {
      localStorage.setItem('neuralclaw_current_view', currentView);
    }
  }, [currentView]);

  if (isAvatarWindow) {
    return (
      <Suspense fallback={null}>
        <AvatarWindow />
      </Suspense>
    );
  }

  if (biometricEnabled && isLocked) {
    return <LockView />;
  }

  if (!setupComplete) {
    return <WizardShell />;
  }

  const renderView = () => {
    switch (currentView) {
      case 'chat': return <ChatPage />;
      case 'settings': return <SettingsPage />;
      case 'memory': return <MemoryPage />;
      case 'knowledge': return <KnowledgePage />;
      case 'tasks': return <TasksPage />;
      case 'workflows': return <WorkflowPage />;
      case 'agents':
        return (
          <Suspense fallback={null}>
            <AgentsPage />
          </Suspense>
        );
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
      <ToastViewport />
    </div>
  );
}
