// NeuralClaw Desktop - Chat Store

import { create } from 'zustand';
import type { ChatMessage, DesktopChatBootstrap, DesktopChatSession, DesktopChatSessionPayload, ToolCall } from '../lib/api';

interface ChatState {
  sessions: DesktopChatSession[];
  activeSessionId: string | null;
  messages: ChatMessage[];
  draft: string;
  initialized: boolean;
  isStreaming: boolean;
  currentStreamContent: string;
  currentToolCalls: ToolCall[];
  pendingResponseSessionId: string | null;

  setBootstrap: (payload: DesktopChatBootstrap) => void;
  setSessionPayload: (payload: DesktopChatSessionPayload) => void;
  setSessions: (sessions: DesktopChatSession[]) => void;
  setDraft: (draft: string) => void;
  addMessage: (msg: ChatMessage, sessionId?: string | null) => void;
  replaceMessages: (msgs: ChatMessage[]) => void;
  clearMessages: () => void;
  setStreaming: (streaming: boolean) => void;
  appendStreamToken: (token: string) => void;
  resetStream: () => void;
  setToolCalls: (calls: ToolCall[]) => void;
  updateToolCall: (name: string, update: Partial<ToolCall>) => void;
  setPendingResponseSessionId: (sessionId: string | null) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  draft: '',
  initialized: false,
  isStreaming: false,
  currentStreamContent: '',
  currentToolCalls: [],
  pendingResponseSessionId: null,

  setBootstrap: (payload) => set({
    sessions: payload.sessions,
    activeSessionId: payload.activeSessionId,
    messages: payload.messages,
    draft: payload.draft,
    initialized: true,
  }),

  setSessionPayload: (payload) => set({
    activeSessionId: payload.activeSessionId,
    messages: payload.messages,
    draft: payload.draft,
    initialized: true,
  }),

  setSessions: (sessions) => set({ sessions }),

  setDraft: (draft) => set({ draft }),

  addMessage: (msg, sessionId) =>
    set((state) => {
      const targetSessionId = sessionId ?? state.activeSessionId;
      if (targetSessionId && state.activeSessionId && targetSessionId !== state.activeSessionId) {
        return {};
      }
      return { messages: [...state.messages, msg] };
    }),

  replaceMessages: (msgs) => set({ messages: msgs }),

  clearMessages: () => set({ messages: [] }),

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  appendStreamToken: (token) =>
    set((state) => ({
      currentStreamContent: state.currentStreamContent + token,
    })),

  resetStream: () =>
    set({ currentStreamContent: '', currentToolCalls: [], isStreaming: false, pendingResponseSessionId: null }),

  setToolCalls: (calls) => set({ currentToolCalls: calls }),

  updateToolCall: (name, update) =>
    set((state) => ({
      currentToolCalls: state.currentToolCalls.map((tc) =>
        tc.name === name ? { ...tc, ...update } : tc,
      ),
    })),

  setPendingResponseSessionId: (sessionId) => set({ pendingResponseSessionId: sessionId }),
}));
