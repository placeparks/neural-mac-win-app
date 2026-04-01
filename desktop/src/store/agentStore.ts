// NeuralClaw Desktop — Agent Store (Zustand)

import { create } from 'zustand';
import {
  AgentDefinition,
  RunningAgent,
  getAgentDefinitions,
  createAgentDefinition,
  deleteAgentDefinition,
  spawnDefinedAgent,
  despawnDefinedAgent,
  getRunningAgents,
} from '../lib/api';

interface AgentStoreState {
  definitions: AgentDefinition[];
  running: RunningAgent[];
  selectedAgent: string | null;
  isCreating: boolean;
  isEditing: string | null;
  loading: boolean;
  error: string | null;

  loadDefinitions: () => Promise<void>;
  loadRunning: () => Promise<void>;
  loadAll: () => Promise<void>;
  createAgent: (defn: Partial<AgentDefinition>) => Promise<{ ok: boolean; error?: string }>;
  deleteAgent: (id: string) => Promise<boolean>;
  spawnAgent: (id: string) => Promise<{ ok: boolean; error?: string }>;
  despawnAgent: (id: string) => Promise<boolean>;
  selectAgent: (name: string | null) => void;
  setCreating: (creating: boolean) => void;
  setEditing: (id: string | null) => void;
  clearError: () => void;
}

export const useAgentStore = create<AgentStoreState>((set, get) => ({
  definitions: [],
  running: [],
  selectedAgent: null,
  isCreating: false,
  isEditing: null,
  loading: false,
  error: null,

  loadDefinitions: async () => {
    try {
      const defs = await getAgentDefinitions();
      set({ definitions: defs });
    } catch {
      // Endpoint may not exist yet
    }
  },

  loadRunning: async () => {
    try {
      const running = await getRunningAgents();
      set({ running });
    } catch {
      // Endpoint may not exist yet
    }
  },

  loadAll: async () => {
    set({ loading: true, error: null });
    await Promise.all([get().loadDefinitions(), get().loadRunning()]);
    set({ loading: false });
  },

  createAgent: async (defn) => {
    try {
      const result = await createAgentDefinition(defn);
      if (result.ok) {
        set({ error: null });
        await get().loadDefinitions();
      } else {
        set({ error: result.error || 'Failed to create agent' });
      }
      return result;
    } catch (e: any) {
      const error = e?.message || 'Failed to create agent';
      set({ error });
      return { ok: false, error };
    }
  },

  deleteAgent: async (id) => {
    try {
      const result = await deleteAgentDefinition(id);
      if (result.ok) {
        await get().loadDefinitions();
      }
      return result.ok;
    } catch {
      return false;
    }
  },

  spawnAgent: async (id) => {
    try {
      const result = await spawnDefinedAgent(id);
      if (result.ok) {
        await get().loadRunning();
      }
      return result;
    } catch (e: any) {
      return { ok: false, error: e?.message || 'Failed to spawn' };
    }
  },

  despawnAgent: async (id) => {
    try {
      const result = await despawnDefinedAgent(id);
      if (result.ok) {
        await get().loadRunning();
      }
      return result.ok;
    } catch {
      return false;
    }
  },

  selectAgent: (name) => set({ selectedAgent: name }),

  setCreating: (creating) => set({ isCreating: creating }),

  setEditing: (id) => set({ isEditing: id }),

  clearError: () => set({ error: null }),
}));
