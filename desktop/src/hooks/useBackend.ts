// NeuralClaw Desktop - WebSocket Backend Connection Hook

import { useEffect, useRef } from 'react';
import { wsManager } from '../lib/ws';
import { useAppStore } from '../store/appStore';
import { useChatStore } from '../store/chatStore';
import { useAvatarState } from '../avatar/useAvatarState';
import { useTaskStore } from '../store/taskStore';
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

    const pollTasks = async () => {
      const taskState = useTaskStore.getState();
      const previousStatuses = { ...taskState.knownStatuses };
      const tasks = await taskState.loadTasks(60);
      for (const task of tasks) {
        const previous = previousStatuses[task.task_id];
        if (!previous && task.status === 'running') {
          useAppStore.getState().pushToast({
            title: 'Task started',
            description: `${task.target_agents.join(', ')} is working on ${task.title}.`,
            level: 'info',
          });
        }
        if (previous && previous !== task.status) {
          if (task.status === 'completed') {
            useAppStore.getState().pushToast({
              title: 'Task completed',
              description: `${task.title} finished for ${task.target_agents.join(', ')}.`,
              level: 'success',
            });
          } else if (task.status === 'partial') {
            useAppStore.getState().pushToast({
              title: 'Task partially completed',
              description: `${task.title} returned mixed agent results.`,
              level: 'warning',
            });
          } else if (task.status === 'failed') {
            useAppStore.getState().pushToast({
              title: 'Task failed',
              description: task.error || `${task.title} failed.`,
              level: 'error',
            });
          }
        }
        if (
          task.requested_model
          && task.effective_model
          && task.requested_model !== task.effective_model
          && previous !== task.status
        ) {
          useAppStore.getState().pushToast({
            title: 'Model failover',
            description: `${task.requested_model} was unavailable. NeuralClaw used ${task.effective_model}.`,
            level: 'warning',
          });
        }
      }
      useTaskStore.getState().noteKnownStatuses();
    };

    void pollTasks();
    const taskTimer = window.setInterval(() => {
      void pollTasks();
    }, 4000);

    return () => {
      unsubStatus();
      unsubDelta();
      unsubResponse();
      unsubComplete();
      unsubError();
      window.clearInterval(taskTimer);
      wsManager.disconnect();
    };
  }, [appendStreamToken, setConnectionStatus, setSessions, setStreaming, resetStream]);

  return { connectionStatus: useAppStore.getState().connectionStatus };
}
