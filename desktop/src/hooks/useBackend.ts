// NeuralClaw Desktop - WebSocket Backend Connection Hook

import { useEffect, useRef } from 'react';
import { wsManager } from '../lib/ws';
import { useAppStore } from '../store/appStore';
import { useChatStore } from '../store/chatStore';
import { useAvatarState } from '../avatar/useAvatarState';
import type { WSEvent } from '../lib/ws';
import { saveDesktopChatMessage } from '../lib/api';

export function useBackend() {
  const { setConnectionStatus } = useAppStore();
  const { appendStreamToken, setStreaming, resetStream, setSessions } = useChatStore();
  const lastFinalizedRef = useRef<string>('');

  useEffect(() => {
    wsManager.connect();

    const unsubStatus = wsManager.on('status', (event: WSEvent) => {
      if (event.content === 'connected') setConnectionStatus('connected');
      else setConnectionStatus('disconnected');
    });

    const unsubDelta = wsManager.on('response_delta', (event: WSEvent) => {
      const avatar = useAvatarState.getState();
      if (!useChatStore.getState().isStreaming) {
        lastFinalizedRef.current = '';
        avatar.setEmotion('thinking');
      } else {
        avatar.setEmotion('neutral');
      }
      avatar.setSpeaking(true);
      setStreaming(true);
      if (event.delta) {
        appendStreamToken(event.delta);
      }
    });

    const finalizeResponse = (content: string, confidence?: number) => {
      const avatar = useAvatarState.getState();
      const chatState = useChatStore.getState();
      const targetSessionId = chatState.pendingResponseSessionId || chatState.activeSessionId;
      if (content) {
        const message = {
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
          confidence,
        } as const;
        chatState.addMessage(message, targetSessionId);
        if (targetSessionId) {
          void saveDesktopChatMessage(targetSessionId, message)
            .then((sessions) => setSessions(sessions))
            .catch(() => undefined);
        }
        avatar.setLatestResponse(content);
      }
      avatar.setSpeaking(false);
      avatar.setEmotion('happy');
      window.setTimeout(() => {
        const nextAvatar = useAvatarState.getState();
        nextAvatar.setEmotion('neutral');
      }, 1800);
      resetStream();
    };

    const unsubResponse = wsManager.on('response', (event: WSEvent) => {
      const signature = `${event.content || ''}|${event.confidence ?? ''}`;
      if (signature && signature === lastFinalizedRef.current) return;
      lastFinalizedRef.current = signature;
      finalizeResponse(event.content || '', event.confidence);
    });

    const unsubComplete = wsManager.on('response_complete', (event: WSEvent) => {
      const signature = `${event.content || ''}|${event.confidence ?? ''}`;
      if (signature && signature === lastFinalizedRef.current) return;
      lastFinalizedRef.current = signature;
      finalizeResponse(event.content || '', event.confidence);
    });

    const unsubError = wsManager.on('error', (event: WSEvent) => {
      const avatar = useAvatarState.getState();
      avatar.setSpeaking(false);
      avatar.setEmotion('surprised');
      if (event.content) {
        const chatState = useChatStore.getState();
        const targetSessionId = chatState.pendingResponseSessionId || chatState.activeSessionId;
        const message = {
          role: 'assistant',
          content: event.content,
          timestamp: new Date().toISOString(),
        } as const;
        chatState.addMessage(message, targetSessionId);
        if (targetSessionId) {
          void saveDesktopChatMessage(targetSessionId, message)
            .then((sessions) => setSessions(sessions))
            .catch(() => undefined);
        }
      }
      resetStream();
    });

    return () => {
      unsubStatus();
      unsubDelta();
      unsubResponse();
      unsubComplete();
      unsubError();
      wsManager.disconnect();
    };
  }, [appendStreamToken, setConnectionStatus, setSessions, setStreaming, resetStream]);

  return { connectionStatus: useAppStore.getState().connectionStatus };
}
