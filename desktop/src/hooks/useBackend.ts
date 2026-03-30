// NeuralClaw Desktop — WebSocket Backend Connection Hook
// Handles real-time chat via WebChatAdapter protocol:
//   response_delta  — streaming token
//   response        — full response
//   response_complete — stream finished (with full content)

import { useEffect } from 'react';
import { wsManager } from '../lib/ws';
import { useAppStore } from '../store/appStore';
import { useChatStore } from '../store/chatStore';
import type { WSEvent } from '../lib/ws';

export function useBackend() {
  const { connectionStatus, setConnectionStatus } = useAppStore();
  const { appendStreamToken, setStreaming, addMessage, resetStream } = useChatStore();

  useEffect(() => {
    wsManager.connect();

    const unsubStatus = wsManager.on('status', (event: WSEvent) => {
      if (event.content === 'connected') setConnectionStatus('connected');
      else setConnectionStatus('disconnected');
    });

    // Streaming token from WebChatAdapter
    const unsubDelta = wsManager.on('response_delta', (event: WSEvent) => {
      setStreaming(true);
      if (event.delta) {
        appendStreamToken(event.delta);
      }
    });

    // Full response (non-streaming)
    const unsubResponse = wsManager.on('response', (event: WSEvent) => {
      const content = event.content || '';
      if (content) {
        addMessage({
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
          confidence: event.confidence,
        });
      }
      resetStream();
    });

    // Stream complete — final assembled response
    const unsubComplete = wsManager.on('response_complete', (event: WSEvent) => {
      const content = event.content || '';
      if (content) {
        addMessage({
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
          confidence: event.confidence,
        });
      }
      resetStream();
    });

    return () => {
      unsubStatus();
      unsubDelta();
      unsubResponse();
      unsubComplete();
      wsManager.disconnect();
    };
  }, []);

  return { connectionStatus };
}
