import { invoke } from '@tauri-apps/api/core';
import { create } from 'zustand';

export type AvatarAnchor = 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left' | 'taskbar' | 'free';
export type AvatarEmotion = 'neutral' | 'thinking' | 'happy' | 'surprised' | 'focused' | 'collaborating';
export type AvatarRenderMode = 'auto' | 'lite' | 'full';

export interface AvatarStatePayload {
  visible: boolean;
  anchor: AvatarAnchor;
  position: { x: number; y: number };
  emotion: AvatarEmotion;
  isSpeaking: boolean;
  modelPath: string;
  scale: number;
  renderMode: AvatarRenderMode;
}

interface AvatarState extends AvatarStatePayload {
  latestResponse: string;
  inputOpen: boolean;
  hydrated: boolean;
  collaborationPulse: boolean;
  responsePreview: string;
  activityLabel: string;
  speakingUntil: number;
  emotionUntil: number;
  hydrate: () => Promise<void>;
  toggleVisible: () => Promise<void>;
  hide: () => Promise<void>;
  setAnchor: (anchor: AvatarAnchor) => Promise<void>;
  setPosition: (x: number, y: number) => Promise<void>;
  anchorToTaskbar: () => Promise<void>;
  setScale: (scale: number) => Promise<void>;
  setModelPath: (modelPath: string) => Promise<void>;
  setRenderMode: (renderMode: AvatarRenderMode) => Promise<void>;
  saveModelFile: (file: File) => Promise<void>;
  setEmotion: (emotion: AvatarEmotion) => void;
  setSpeaking: (isSpeaking: boolean) => void;
  setLatestResponse: (content: string) => void;
  setInputOpen: (open: boolean) => void;
  setCollaborationPulse: (value: boolean) => void;
  setResponsePreview: (content: string) => void;
  setActivityLabel: (content: string) => void;
  pulseSpeaking: (durationMs?: number) => void;
  openMainApp: (targetView?: string) => Promise<void>;
}

const defaultState: AvatarStatePayload = {
  visible: false,
  anchor: 'bottom-right',
  position: { x: 100, y: 100 },
  emotion: 'neutral',
  isSpeaking: false,
  modelPath: '',
  scale: 1,
  renderMode: 'auto',
};

export const useAvatarState = create<AvatarState>((set, get) => ({
  ...defaultState,
  latestResponse: '',
  inputOpen: false,
  hydrated: false,
  collaborationPulse: false,
  responsePreview: '',
  activityLabel: 'Ready',
  speakingUntil: 0,
  emotionUntil: 0,

  hydrate: async () => {
    try {
      const state = await invoke<AvatarStatePayload>('get_avatar_state');
      set({ ...state, hydrated: true });
    } catch {
      set({ hydrated: true });
    }
  },

  toggleVisible: async () => {
    const state = await invoke<AvatarStatePayload>('toggle_avatar_window');
    set(state);
  },

  hide: async () => {
    const state = await invoke<AvatarStatePayload>('hide_avatar_window');
    set(state);
  },

  setAnchor: async (anchor) => {
    if (anchor === 'taskbar') {
      const state = await invoke<AvatarStatePayload>('anchor_to_taskbar');
      set(state);
      return;
    }
    const state = await invoke<AvatarStatePayload>('set_avatar_anchor', { anchor });
    set(state);
  },

  setPosition: async (x, y) => {
    const state = await invoke<AvatarStatePayload>('set_avatar_position', { x, y });
    set(state);
  },

  anchorToTaskbar: async () => {
    const state = await invoke<AvatarStatePayload>('anchor_to_taskbar');
    set(state);
  },

  setScale: async (scale) => {
    const state = await invoke<AvatarStatePayload>('update_avatar_settings', { scale });
    set(state);
  },

  setModelPath: async (modelPath) => {
    const state = await invoke<AvatarStatePayload>('update_avatar_settings', { modelPath });
    set(state);
  },

  setRenderMode: async (renderMode) => {
    const state = await invoke<AvatarStatePayload>('update_avatar_settings', { renderMode });
    set(state);
  },

  saveModelFile: async (file) => {
    const bytes = Array.from(new Uint8Array(await file.arrayBuffer()));
    const modelPath = await invoke<string>('save_avatar_model', {
      fileName: file.name,
      bytes,
    });
    await get().setModelPath(modelPath);
  },

  setEmotion: (emotion) => set({ emotion, emotionUntil: Date.now() + 1800 }),

  setSpeaking: (isSpeaking) => set({ isSpeaking }),

  setLatestResponse: (content) => set({ latestResponse: content }),

  setInputOpen: (open) => set({ inputOpen: open }),

  setCollaborationPulse: (value) => set({ collaborationPulse: value }),

  setResponsePreview: (content) => set({ responsePreview: content }),

  setActivityLabel: (content) => set({ activityLabel: content }),

  pulseSpeaking: (durationMs = 2400) => {
    const until = Date.now() + durationMs;
    set({ isSpeaking: true, speakingUntil: until });
    window.setTimeout(() => {
      const current = get().speakingUntil;
      if (current <= Date.now()) {
        set({ isSpeaking: false });
      }
    }, durationMs + 80);
  },

  openMainApp: async (targetView) => {
    await invoke('open_main_window', { targetView });
  },
}));
