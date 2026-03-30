// NeuralClaw Desktop — Chat Hook
// Uses WebSocket for real-time chat via the WebChatAdapter

import { useCallback } from 'react';
import { useChatStore } from '../store/chatStore';
import { wsManager } from '../lib/ws';
import type { ChatMessage } from '../lib/api';

export function useChat() {
  const {
    messages,
    isStreaming,
    addMessage,
    clearMessages,
    setStreaming,
    resetStream,
  } = useChatStore();

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isStreaming) return;

    const userMsg: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    };
    addMessage(userMsg);
    setStreaming(true);

    // Send via WebSocket (matches WebChatAdapter protocol: { content: "..." })
    if (wsManager.connected) {
      wsManager.send(content);
    } else {
      // Fallback: show error if WS not connected
      addMessage({
        role: 'assistant',
        content: '⚠️ Not connected to backend. Make sure NeuralClaw is running with `python -m neuralclaw gateway --web-port 8099`',
        timestamp: new Date().toISOString(),
      });
      resetStream();
    }
  }, [isStreaming, addMessage, setStreaming, resetStream]);

  const loadHistory = useCallback(async () => {
    // WebSocket-based chat doesn't have a history endpoint
    // Messages are stored in-memory via Zustand
  }, []);

  const clearChatHistory = useCallback(async () => {
    clearMessages();
  }, [clearMessages]);

  return {
    messages,
    isStreaming,
    sendMessage,
    loadHistory,
    clearChatHistory,
  };
}
