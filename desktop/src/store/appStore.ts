// NeuralClaw Desktop — Global App State (Zustand)

import { create } from 'zustand';
import { deletePersistedValue, getPersistedValue, setPersistedValue } from '../lib/persistence';

export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting';
export type AppView = 'lock' | 'wizard' | 'app';
export type ToastLevel = 'info' | 'success' | 'error' | 'warning';

export interface AppToast {
  id: string;
  title: string;
  description: string;
  level: ToastLevel;
  createdAt: number;
}

interface AppState {
  // Connection
  connectionStatus: ConnectionStatus;
  realtimeStatus: ConnectionStatus;
  setConnectionStatus: (status: ConnectionStatus) => void;
  setRealtimeStatus: (status: ConnectionStatus) => void;

  // Auth
  isLocked: boolean;
  biometricEnabled: boolean;
  setLocked: (locked: boolean) => void;
  setBiometricEnabled: (enabled: boolean) => void;

  // View routing
  appView: AppView;
  setAppView: (view: AppView) => void;

  // Setup
  setupComplete: boolean;
  persistenceHydrated: boolean;
  setSetupComplete: (complete: boolean) => void;
  hydratePersistence: () => Promise<void>;

  // Backend
  backendVersion: string;
  backendUptime: number;
  setBackendInfo: (version: string, uptime: number) => void;

  // Toasts
  toasts: AppToast[];
  pushToast: (toast: Omit<AppToast, 'id' | 'createdAt'>) => void;
  removeToast: (id: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  connectionStatus: 'disconnected',
  realtimeStatus: 'disconnected',
  setConnectionStatus: (status) => set({ connectionStatus: status }),
  setRealtimeStatus: (status) => set({ realtimeStatus: status }),

  isLocked: false,
  biometricEnabled: false,
  setLocked: (locked) => set({ isLocked: locked }),
  setBiometricEnabled: (enabled) => set({ biometricEnabled: enabled }),

  appView: 'wizard',
  setAppView: (view) => set({ appView: view }),

  setupComplete: false,
  persistenceHydrated: false,
  setSetupComplete: (complete) => {
    void (complete
      ? setPersistedValue('neuralclaw_setup_complete', true)
      : deletePersistedValue('neuralclaw_setup_complete'));
    set({ setupComplete: complete });
  },
  hydratePersistence: async () => {
    const setupComplete = await getPersistedValue<boolean>('neuralclaw_setup_complete', false);
    set({ setupComplete, persistenceHydrated: true });
  },

  backendVersion: '',
  backendUptime: 0,
  setBackendInfo: (version, uptime) => set({ backendVersion: version, backendUptime: uptime }),

  toasts: [],
  pushToast: (toast) => set((state) => ({
    toasts: [
      ...state.toasts,
      {
        ...toast,
        id: Math.random().toString(36).slice(2, 10),
        createdAt: Date.now(),
      },
    ].slice(-6),
  })),
  removeToast: (id) => set((state) => ({
    toasts: state.toasts.filter((toast) => toast.id !== id),
  })),
}));
