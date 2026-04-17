// NeuralClaw Desktop — Wizard Store

import { create } from 'zustand';
import type { ProviderId } from '../lib/theme';

interface WizardState {
  currentStep: number;
  totalSteps: number;

  // Step 2: Providers
  selectedProviders: ProviderId[];
  toggleProvider: (id: ProviderId) => void;

  // Step 3: API Keys
  apiKeys: Record<string, string>;
  apiEndpoints: Record<string, string>;
  setApiKey: (provider: string, key: string) => void;
  setApiEndpoint: (provider: string, endpoint: string) => void;
  currentKeyProvider: number;
  setCurrentKeyProvider: (idx: number) => void;

  // Step 4: Model
  selectedModel: string;
  setSelectedModel: (model: string) => void;
  modelRoles: {
    primary: string;
    fast: string;
    micro: string;
  };
  setModelRole: (role: 'primary' | 'fast' | 'micro', model: string) => void;

  // Step 5: Channels
  selectedChannels: string[];
  toggleChannel: (channel: string) => void;
  channelTokens: Record<string, string>;
  setChannelToken: (channel: string, token: string) => void;

  // Step 6: Features
  features: Record<string, boolean>;
  toggleFeature: (feature: string) => void;

  // Navigation
  nextStep: () => void;
  prevStep: () => void;
  goToStep: (step: number) => void;
  reset: () => void;
}

export const useWizardStore = create<WizardState>((set) => ({
  currentStep: 1,
  totalSteps: 7,

  selectedProviders: [],
  toggleProvider: (id) =>
    set((state) => ({
      selectedProviders: state.selectedProviders.includes(id)
        ? state.selectedProviders.filter((p) => p !== id)
        : [...state.selectedProviders, id],
    })),

  apiKeys: {},
  apiEndpoints: {},
  setApiKey: (provider, key) =>
    set((state) => ({
      apiKeys: { ...state.apiKeys, [provider]: key },
    })),
  setApiEndpoint: (provider, endpoint) =>
    set((state) => ({
      apiEndpoints: { ...state.apiEndpoints, [provider]: endpoint },
    })),
  currentKeyProvider: 0,
  setCurrentKeyProvider: (idx) => set({ currentKeyProvider: idx }),

  selectedModel: '',
  setSelectedModel: (model) =>
    set((state) => ({
      selectedModel: model,
      modelRoles: {
        primary: model,
        fast: state.modelRoles.fast || model,
        micro: state.modelRoles.micro || model,
      },
    })),
  modelRoles: {
    primary: '',
    fast: '',
    micro: '',
  },
  setModelRole: (role, model) =>
    set((state) => ({
      selectedModel: role === 'primary' ? model : state.selectedModel,
      modelRoles: {
        ...state.modelRoles,
        [role]: model,
      },
    })),

  selectedChannels: [],
  toggleChannel: (channel) =>
    set((state) => ({
      selectedChannels: state.selectedChannels.includes(channel)
        ? state.selectedChannels.filter((c) => c !== channel)
        : [...state.selectedChannels, channel],
    })),
  channelTokens: {},
  setChannelToken: (channel, token) =>
    set((state) => ({
      channelTokens: { ...state.channelTokens, [channel]: token },
    })),

  features: {
    memory: true,
    knowledge_base: true,
    workflows: false,
    dashboard: true,
    biometric_lock: true,
  },
  toggleFeature: (feature) =>
    set((state) => ({
      features: {
        ...state.features,
        [feature]: !state.features[feature],
      },
    })),

  nextStep: () =>
    set((state) => ({
      currentStep: Math.min(state.currentStep + 1, state.totalSteps),
    })),
  prevStep: () =>
    set((state) => ({
      currentStep: Math.max(state.currentStep - 1, 1),
    })),
  goToStep: (step) => set({ currentStep: step }),
  reset: () =>
    set({
      currentStep: 1,
      selectedProviders: [],
      apiKeys: {},
      apiEndpoints: {},
      currentKeyProvider: 0,
      selectedModel: '',
      modelRoles: {
        primary: '',
        fast: '',
        micro: '',
      },
      selectedChannels: [],
      channelTokens: {},
      features: {
        memory: true,
        knowledge_base: true,
        workflows: false,
        dashboard: true,
        biometric_lock: true,
      },
    }),
}));
