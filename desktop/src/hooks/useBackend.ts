// NeuralClaw Desktop - WebSocket Backend Connection Hook

import { useEffect, useRef } from 'react';
import { wsManager } from '../lib/ws';
import { useAppStore } from '../store/appStore';
import { useChatStore } from '../store/chatStore';
import { useAvatarState } from '../avatar/useAvatarState';
import { useTaskStore } from '../store/taskStore';
import type { WSEvent } from '../lib/ws';
import { saveDesktopChatMessage } from '../lib/api';
import { maybeSpeakAssistantReply, stopAssistantSpeech } from '../lib/voiceAssistant';

export function useBackend() {
  const { setRealtimeStatus } = useAppStore();
  const { appendStreamToken, setStreaming, resetStream, setSessions } = useChatStore();
  const lastFinalizedRef = useRef<string>('');

  useEffect(() => {
    wsManager.connect();

    const unsubStatus = wsManager.on('status', (event: WSEvent) => {
      if (event.content === 'connected') {
        setRealtimeStatus('connected');
      } else if (event.content === 'reconnecting') {
        setRealtimeStatus('connecting');
      } else {
        setRealtimeStatus('disconnected');
      }
    });

    // After WS reconnects, the gateway may have restarted with different
    // state. Re-pull tasks (sessions/agents are pulled lazily) so the UI
    // reflects reality instead of stale local cache.
    const unsubReconnected = wsManager.on('reconnected', () => {
      void useTaskStore.getState().loadTasks(60);
      // If a chat send was in flight when the gateway died, abort the
      // streaming spinner so the user can retry.
      const chatState = useChatStore.getState();
      if (chatState.isStreaming) {
        chatState.resetStream();
      }
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
        avatar.setResponsePreview(content);
        avatar.setActivityLabel('Answered');
        avatar.pulseSpeaking(Math.min(7000, Math.max(2200, content.length * 38)));
        void maybeSpeakAssistantReply(content);
      }
      avatar.setEmotion('happy');
      const neutralAt = useAvatarState.getState().emotionUntil;
      window.setTimeout(() => {
        const nextAvatar = useAvatarState.getState();
        if (nextAvatar.emotionUntil === neutralAt) {
          nextAvatar.setEmotion('neutral');
        }
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
      stopAssistantSpeech();
      avatar.setSpeaking(false);
      avatar.setEmotion('surprised');
      avatar.setActivityLabel('Needs attention');
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
        avatar.setLatestResponse(event.content);
        avatar.setResponsePreview(event.content);
      }
      resetStream();
    });

    const pollTasks = async () => {
      const taskState = useTaskStore.getState();
      const previousStatuses = { ...taskState.knownStatuses };
      const tasks = await taskState.loadTasks(60);
      if (taskState.selectedTaskId) {
        void taskState.loadTask(taskState.selectedTaskId);
      }
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
      unsubReconnected();
      unsubDelta();
      unsubResponse();
      unsubComplete();
      unsubError();
      window.clearInterval(taskTimer);
      wsManager.disconnect();
    };
  }, [appendStreamToken, setRealtimeStatus, setSessions, setStreaming, resetStream]);

  return { connectionStatus: useAppStore.getState().connectionStatus };
}
