// NeuralClaw Desktop - Main App Component

import { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { useAppStore } from './store/appStore';
import { useHealth } from './hooks/useHealth';
import { useBackend } from './hooks/useBackend';
import { getProviderStatus } from './lib/api';
import Sidebar from './components/layout/Sidebar';
import ToastViewport from './components/layout/ToastViewport';
import WizardShell from './wizard/WizardShell';
import LockView from './views/LockView';
import ChatPage from './views/ChatPage';
import { deletePersistedValue, getPersistedValue, setPersistedValue } from './lib/persistence';

const ConnectionsPage = lazy(() => import('./views/ConnectionsPage'));
const SettingsPage = lazy(() => import('./views/SettingsPage'));
const MemoryPage = lazy(() => import('./views/MemoryPage'));
const KnowledgePage = lazy(() => import('./views/KnowledgePage'));
const TasksPage = lazy(() => import('./views/TasksPage'));
const WorkflowPage = lazy(() => import('./views/WorkflowPage'));
const DashboardPage = lazy(() => import('./views/DashboardPage'));
const DatabasePage = lazy(() => import('./views/DatabasePage'));
const WorkspacePage = lazy(() => import('./views/WorkspacePage'));
const AboutPage = lazy(() => import('./views/AboutPage'));
const CommandPalette = lazy(() => import('./components/CommandPalette'));
const AgentsPage = lazy(() => import('./views/AgentsPage'));
const AvatarWindow = lazy(() => import('./avatar/AvatarWindow'));

const currentWindow = getCurrentWebviewWindow();
const currentNativeWindow = getCurrentWindow();
const isAvatarWindow = currentWindow.label === 'avatar' || window.location.pathname === '/avatar';

function ViewFallback() {
  return (
    <div className="app-content" style={{ display: 'grid', placeItems: 'center', minHeight: '100%' }}>
      <div className="empty-state" style={{ padding: 24 }}>
        <span className="spinner spinner-lg" />
        <p>Loading surface...</p>
      </div>
    </div>
  );
}

export default function App() {
  const { setupComplete, persistenceHydrated, isLocked, biometricEnabled, hydratePersistence } = useAppStore();
  const [currentView, setCurrentView] = useState('chat');
  const [viewHydrated, setViewHydrated] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  useHealth();
  useBackend();

  useEffect(() => {
    if (isAvatarWindow) return;
    void hydratePersistence();
    void getPersistedValue<string>('neuralclaw_current_view', 'chat').then((value) => {
      setCurrentView(value || 'chat');
      setViewHydrated(true);
    });
  }, [hydratePersistence]);

  // Fresh-install detection: if localStorage says setup is complete but the
  // backend has no providers configured, the user reinstalled or cleared data.
  // Reset the flag so the wizard runs again.
  const freshInstallChecked = useRef(false);
  useEffect(() => {
    if (isAvatarWindow || freshInstallChecked.current) return;
    freshInstallChecked.current = true;
    if (!setupComplete) return; // Already showing wizard — nothing to check.
    (async () => {
      try {
        const status = await getProviderStatus();
        const primary = status.primary || '';
        const primaryProvider = status.providers.find((provider) => provider.name === primary);
        const hasApiKey = Boolean(primaryProvider?.has_key);
        const hasLocalProvider = primary === 'local' || primary === 'meta';
        // No key AND not a local provider = definitely a fresh install
        if (!hasApiKey && !hasLocalProvider) {
          useAppStore.getState().setSetupComplete(false);
          // Also clear leftover navigation so wizard starts at step 1
          void deletePersistedValue('neuralclaw_current_view');
        }
      } catch {
        // Backend not ready yet — leave the existing state
      }
    })();
  }, [setupComplete]);

  // Silent startup update check — runs once, non-blocking
  const updateChecked = useRef(false);
  useEffect(() => {
    if (isAvatarWindow || updateChecked.current) return;
    updateChecked.current = true;
    (async () => {
      try {
        const { check } = await import('@tauri-apps/plugin-updater');
        const update = await check();
        if (update) {
          useAppStore.getState().pushToast({
            title: 'Update available',
            description: `NeuralClaw v${update.version} is ready — go to About to install.`,
            level: 'info',
          });
        }
      } catch {
        // Silently ignore — the user can always check manually from About
      }
    })();
  }, []);

  useEffect(() => {
    if (isAvatarWindow) return;
    const handleNavigate = (event: Event) => {
      const nextView = (event as CustomEvent<string>).detail || 'chat';
      setCurrentView(nextView);
    };
    const handleCommandPalette = () => setCommandPaletteOpen(true);
    window.addEventListener('neuralclaw:navigate', handleNavigate as EventListener);
    window.addEventListener('neuralclaw:command-palette', handleCommandPalette);
    return () => {
      window.removeEventListener('neuralclaw:navigate', handleNavigate as EventListener);
      window.removeEventListener('neuralclaw:command-palette', handleCommandPalette);
    };
  }, []);

  useEffect(() => {
    if (isAvatarWindow) return;
    let unlisten: (() => void) | undefined;
    void currentNativeWindow.onCloseRequested((event) => {
      event.preventDefault();
      void currentNativeWindow.hide();
    }).then((dispose) => {
      unlisten = dispose;
    });
    return () => {
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!isAvatarWindow && viewHydrated) {
      void setPersistedValue('neuralclaw_current_view', currentView);
    }
  }, [currentView, viewHydrated]);

  useEffect(() => {
    if (isAvatarWindow || !setupComplete) return;
    const preloadViews = () => {
      void import('./views/DashboardPage');
      void import('./views/TasksPage');
      void import('./views/DatabasePage');
      void import('./views/ConnectionsPage');
      void import('./views/SettingsPage');
      void import('./components/CommandPalette');
    };

    if ('requestIdleCallback' in window) {
      const callbackId = window.requestIdleCallback(() => preloadViews());
      return () => window.cancelIdleCallback(callbackId);
    }

    const timeoutId = globalThis.setTimeout(preloadViews, 1200);
    return () => globalThis.clearTimeout(timeoutId);
  }, [setupComplete]);

  if (!isAvatarWindow && (!persistenceHydrated || !viewHydrated)) {
    return null;
  }

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
      case 'connections': return <ConnectionsPage />;
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
      case 'database': return <DatabasePage />;
      case 'workspace': return <WorkspacePage />;
      case 'about': return <AboutPage />;
      default: return <ChatPage />;
    }
  };

  return (
    <div className="app-layout">
      <Sidebar currentView={currentView} onNavigate={setCurrentView} />
      <main className="app-main">
        <Suspense fallback={<ViewFallback />}>
          {renderView()}
        </Suspense>
      </main>
      <Suspense fallback={null}>
        <CommandPalette
          open={commandPaletteOpen}
          onClose={() => setCommandPaletteOpen(false)}
          onNavigate={setCurrentView}
        />
      </Suspense>
      <ToastViewport />
    </div>
  );
}
