// NeuralClaw Desktop - Chat Hook
// Persists local chat sessions while using WebSocket for live responses.

import { useCallback, useEffect, useRef } from 'react';
import {
  ChatMessage,
  clearDesktopChatSession,
  createDesktopChatSession,
  deleteDesktopChatSession,
  getChatBootstrap,
  renameDesktopChatSession,
  saveDesktopChatDraft,
  saveDesktopChatMessage,
  switchDesktopChatSession,
} from '../lib/api';
import { wsManager } from '../lib/ws';
import { useChatStore } from '../store/chatStore';

const DRAFT_SAVE_DELAY = 250;

export function useChat() {
  const {
    sessions,
    activeSessionId,
    messages,
    draft,
    initialized,
    isStreaming,
    currentStreamContent,
    addMessage,
    clearMessages,
    resetStream,
    setBootstrap,
    setDraft,
    setPendingResponseSessionId,
    setSessionPayload,
    setSessions,
    setStreaming,
  } = useChatStore();
  const draftTimerRef = useRef<number | null>(null);

  const clearScheduledDraftSave = useCallback(() => {
    if (draftTimerRef.current) {
      window.clearTimeout(draftTimerRef.current);
      draftTimerRef.current = null;
    }
  }, []);

  const flushDraft = useCallback(async (sessionId: string | null, content: string) => {
    if (!sessionId) return;
    clearScheduledDraftSave();
    await saveDesktopChatDraft(sessionId, content);
  }, [clearScheduledDraftSave]);

  const scheduleDraftSave = useCallback((sessionId: string | null, content: string) => {
    clearScheduledDraftSave();
    if (!sessionId) return;
    draftTimerRef.current = window.setTimeout(() => {
      void saveDesktopChatDraft(sessionId, content);
      draftTimerRef.current = null;
    }, DRAFT_SAVE_DELAY);
  }, [clearScheduledDraftSave]);

  useEffect(() => () => {
    clearScheduledDraftSave();
  }, [clearScheduledDraftSave]);

  const loadHistory = useCallback(async () => {
    const bootstrap = await getChatBootstrap();
    setBootstrap(bootstrap);
  }, [setBootstrap]);

  const createSession = useCallback(async () => {
    if (isStreaming) return activeSessionId ?? '';
    if (activeSessionId) {
      await flushDraft(activeSessionId, draft);
    }
    const bootstrap = await createDesktopChatSession();
    resetStream();
    setBootstrap(bootstrap);
    return bootstrap.activeSessionId;
  }, [activeSessionId, draft, flushDraft, isStreaming, resetStream, setBootstrap]);

  const switchSession = useCallback(async (sessionId: string) => {
    if (isStreaming) return;
    if (sessionId === activeSessionId) return;
    if (activeSessionId) {
      await flushDraft(activeSessionId, draft);
    }
    const payload = await switchDesktopChatSession(sessionId);
    setSessionPayload(payload);
    resetStream();
  }, [activeSessionId, draft, flushDraft, isStreaming, resetStream, setSessionPayload]);

  const renameSession = useCallback(async (sessionId: string, title: string) => {
    if (isStreaming) return;
    const sessions = await renameDesktopChatSession(sessionId, title);
    setSessions(sessions);
  }, [isStreaming, setSessions]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (isStreaming) return;
    const bootstrap = await deleteDesktopChatSession(sessionId);
    resetStream();
    setBootstrap(bootstrap);
  }, [isStreaming, resetStream, setBootstrap]);

  const updateDraft = useCallback((content: string) => {
    setDraft(content);
    scheduleDraftSave(activeSessionId, content);
  }, [activeSessionId, scheduleDraftSave, setDraft]);

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isStreaming) return;

    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = await createSession();
    }

    const userMsg: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    };

    addMessage(userMsg, sessionId);
    setDraft('');
    setPendingResponseSessionId(sessionId);
    setStreaming(true);
    await flushDraft(sessionId, '');
    const nextSessions = await saveDesktopChatMessage(sessionId, userMsg);
    setSessions(nextSessions);

    if (wsManager.connected) {
      wsManager.send(content);
      return;
    }

    const errorMsg: ChatMessage = {
      role: 'assistant',
      content: 'Connection to the backend is unavailable. Start NeuralClaw and retry.',
      timestamp: new Date().toISOString(),
    };
    addMessage(errorMsg, sessionId);
    const erroredSessions = await saveDesktopChatMessage(sessionId, errorMsg);
    setSessions(erroredSessions);
    resetStream();
  }, [
    activeSessionId,
    addMessage,
    createSession,
    flushDraft,
    isStreaming,
    resetStream,
    setDraft,
    setPendingResponseSessionId,
    setSessions,
    setStreaming,
  ]);

  const persistAssistantMessage = useCallback(async (message: ChatMessage, sessionId?: string | null) => {
    const targetSessionId = sessionId ?? useChatStore.getState().pendingResponseSessionId ?? useChatStore.getState().activeSessionId;
    if (!targetSessionId) return;
    addMessage(message, targetSessionId);
    const nextSessions = await saveDesktopChatMessage(targetSessionId, message);
    setSessions(nextSessions);
  }, [addMessage, setSessions]);

  const clearChatHistory = useCallback(async () => {
    if (isStreaming) return;
    if (!activeSessionId) return;
    await flushDraft(activeSessionId, '');
    const nextSessions = await clearDesktopChatSession(activeSessionId);
    clearMessages();
    setDraft('');
    resetStream();
    setSessions(nextSessions);
  }, [activeSessionId, clearMessages, flushDraft, isStreaming, resetStream, setDraft, setSessions]);

  return {
    sessions,
    activeSessionId,
    messages,
    draft,
    initialized,
    isStreaming,
    currentStreamContent,
    sendMessage,
    loadHistory,
    clearChatHistory,
    createSession,
    switchSession,
    renameSession,
    deleteSession,
    updateDraft,
    persistAssistantMessage,
  };
}
