// NeuralClaw Desktop — Chat Store

import { create } from 'zustand';
import type { ChatMessage, ToolCall } from '../lib/api';

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentStreamContent: string;
  currentToolCalls: ToolCall[];

  addMessage: (msg: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  clearMessages: () => void;
  setStreaming: (streaming: boolean) => void;
  appendStreamToken: (token: string) => void;
  resetStream: () => void;
  setToolCalls: (calls: ToolCall[]) => void;
  updateToolCall: (name: string, update: Partial<ToolCall>) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  currentStreamContent: '',
  currentToolCalls: [],

  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),

  setMessages: (msgs) => set({ messages: msgs }),

  clearMessages: () => set({ messages: [] }),

  setStreaming: (streaming) => set({ isStreaming: streaming }),

  appendStreamToken: (token) =>
    set((state) => ({
      currentStreamContent: state.currentStreamContent + token,
    })),

  resetStream: () =>
    set({ currentStreamContent: '', currentToolCalls: [], isStreaming: false }),

  setToolCalls: (calls) => set({ currentToolCalls: calls }),

  updateToolCall: (name, update) =>
    set((state) => ({
      currentToolCalls: state.currentToolCalls.map((tc) =>
        tc.name === name ? { ...tc, ...update } : tc
      ),
    })),
}));
