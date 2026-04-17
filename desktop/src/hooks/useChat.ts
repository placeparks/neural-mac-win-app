// NeuralClaw Desktop - Chat Hook
// Persists local chat sessions while using WebSocket for live responses.

import { useCallback, useEffect, useRef } from 'react';
import {
  ChatAttachmentPayload,
  ChatMessage,
  ChatSessionMetadata,
  clearDesktopChatSession,
  createDesktopChatSession,
  createDesktopChatSessionWithMetadata,
  deleteDesktopChatSession,
  getChatBootstrap,
  getProviderDefaults,
  getPrimaryProviderDefaults,
  renameDesktopChatSession,
  resetAllDesktopChatSessions,
  saveDesktopChatDraft,
  saveDesktopChatMessage,
  sendChatMessage,
  switchDesktopChatSession,
  updateDesktopChatSessionMetadata,
} from '../lib/api';
import { useChatStore } from '../store/chatStore';
import { useAvatarState } from '../avatar/useAvatarState';
import { maybeSpeakAssistantReply, stopAssistantSpeech } from '../lib/voiceAssistant';

const DRAFT_SAVE_DELAY = 250;

export function useChat() {
  const {
    sessions,
    activeSessionId,
    messages,
    draft,
    metadata,
    initialized,
    isStreaming,
    currentStreamContent,
    addMessage,
    clearMessages,
    resetStream,
    setBootstrap,
    setDraft,
    setMetadata,
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

  const createSession = useCallback(async (title?: string, nextMetadata?: ChatSessionMetadata) => {
    if (isStreaming) return activeSessionId ?? '';
    if (activeSessionId) {
      await flushDraft(activeSessionId, draft);
    }
    const bootstrap = nextMetadata
      ? await createDesktopChatSessionWithMetadata(title, nextMetadata)
      : await createDesktopChatSession(title);
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

  const setSessionMetadata = useCallback(async (nextMetadata: ChatSessionMetadata) => {
    if (!activeSessionId || isStreaming) return;
    const sessions = await updateDesktopChatSessionMetadata(activeSessionId, nextMetadata);
    setSessions(sessions);
    setMetadata(nextMetadata);
  }, [activeSessionId, isStreaming, setMetadata, setSessions]);

  const startAgentConversation = useCallback(async (agentName: string) => {
    if (!agentName.trim()) return '';
    const existing = sessions.find((session) => session.metadata?.targetAgent === agentName);
    if (existing) {
      await switchSession(existing.sessionId);
      return existing.sessionId;
    }
    let resolvedProvider = metadata.selectedProvider || '';
    let resolvedModel = metadata.selectedModel || '';
    let resolvedBaseUrl = metadata.baseUrl || '';
    if (!resolvedBaseUrl) {
      try {
        const defaults = await getProviderDefaults(resolvedProvider || 'primary');
        resolvedProvider = resolvedProvider || defaults.provider || defaults.primary;
        resolvedModel = resolvedModel || defaults.model || '';
        resolvedBaseUrl = defaults.baseUrl || '';
      } catch {
        try {
          const defaults = await getPrimaryProviderDefaults();
          resolvedProvider = resolvedProvider || defaults.provider || defaults.primary;
          resolvedModel = resolvedModel || defaults.model || '';
          resolvedBaseUrl = defaults.baseUrl || '';
        } catch {
          resolvedBaseUrl = '';
        }
      }
    }
    return createSession(`Agent: ${agentName}`, {
      targetAgent: agentName,
      selectedProvider: resolvedProvider || null,
      selectedModel: resolvedModel || null,
      baseUrl: resolvedBaseUrl || null,
    });
  }, [createSession, metadata.baseUrl, metadata.selectedModel, metadata.selectedProvider, sessions, switchSession]);

  const updateDraft = useCallback((content: string) => {
    setDraft(content);
    scheduleDraftSave(activeSessionId, content);
  }, [activeSessionId, scheduleDraftSave, setDraft]);

  const sendMessage = useCallback(async (content: string, attachments: ChatAttachmentPayload[] = []) => {
    if ((!content.trim() && attachments.length === 0) || isStreaming) return;
    const avatar = useAvatarState.getState();
    stopAssistantSpeech();
    avatar.setEmotion('thinking');
    avatar.setSpeaking(false);
    avatar.setActivityLabel(attachments.length ? `Reviewing ${attachments.length} attachment${attachments.length === 1 ? '' : 's'}` : 'Thinking');
    avatar.setResponsePreview(content.trim() || 'Working from attachments');

    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = await createSession(undefined, metadata);
    }

    const attachmentSummary = attachments.length
      ? `\n\nAttachments:\n${attachments.map((item) => `- ${item.name}`).join('\n')}`
      : '';

    const userMsg: ChatMessage = {
      role: 'user',
      content: `${content}${attachmentSummary}`.trim(),
      timestamp: new Date().toISOString(),
    };

    addMessage(userMsg, sessionId);
    setDraft('');
    setPendingResponseSessionId(sessionId);
    setStreaming(true);
    await flushDraft(sessionId, '');
    const nextSessions = await saveDesktopChatMessage(sessionId, userMsg);
    setSessions(nextSessions);
    try {
      const media = attachments
        .filter((item) => item.kind === 'image')
        .map((item) => ({
          type: 'image',
          name: item.name,
          content: item.content,
          mime_type: item.mimeType,
        }));
      const documents = attachments
        .filter((item) => item.kind === 'document')
        .map((item) => ({
          name: item.name,
          content: item.content,
          mime_type: item.mimeType,
        }));

      const response = await sendChatMessage({
        content: content.trim() || 'Please review the attached files and respond with the most useful summary or action.',
        targetAgent: metadata.targetAgent || null,
        model: metadata.selectedModel || null,
        provider: metadata.selectedProvider || null,
        baseUrl: metadata.baseUrl || null,
        sessionId,
        teachingMode: metadata.teachingMode ?? null,
        autonomyMode: metadata.autonomyMode || null,
        projectContextId: metadata.projectContextId || null,
        channelStyleProfile: metadata.channelStyleProfile || null,
        media,
        documents,
      });

      if (response.effective_model || response.fallback_reason) {
        const nextMetadata = {
          ...metadata,
          selectedModel: metadata.selectedModel || response.requested_model || metadata.selectedModel || null,
          effectiveModel: response.effective_model || metadata.effectiveModel || null,
          fallbackReason: response.fallback_reason || null,
          teachingMode: metadata.teachingMode ?? null,
          autonomyMode: metadata.autonomyMode || null,
          projectContextId: metadata.projectContextId || null,
          channelStyleProfile: metadata.channelStyleProfile || null,
        };
        await updateDesktopChatSessionMetadata(sessionId, nextMetadata);
        setMetadata(nextMetadata);
      }

      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.ok
          ? (response.response || 'Done.')
          : (response.error || 'Failed to send message.'),
        timestamp: new Date().toISOString(),
        metadata: {
          requestedModel: response.requested_model || null,
          effectiveModel: response.effective_model || null,
          fallbackReason: response.fallback_reason || null,
          memoryProvenance: response.memory_provenance || [],
          memoryScopes: response.memory_scopes || [],
          confidenceContract: response.confidence_contract || {},
        },
      };

      addMessage(assistantMessage, sessionId);
      const updatedSessions = await saveDesktopChatMessage(sessionId, assistantMessage);
      setSessions(updatedSessions);

      avatar.setLatestResponse(assistantMessage.content);
      avatar.setResponsePreview(assistantMessage.content);
      avatar.setEmotion(response.ok ? 'happy' : 'surprised');
      avatar.setActivityLabel(response.ok ? 'Answered' : 'Needs attention');
      if (response.ok) {
        avatar.pulseSpeaking(Math.min(7000, Math.max(2200, assistantMessage.content.length * 38)));
        void maybeSpeakAssistantReply(assistantMessage.content);
      }
      else avatar.setSpeaking(false);
    } catch (error: any) {
      stopAssistantSpeech();
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: error?.message || 'Connection to the backend is unavailable. Start NeuralClaw and retry.',
        timestamp: new Date().toISOString(),
        metadata: {
          memoryProvenance: [],
          memoryScopes: [],
          confidenceContract: {},
        },
      };
      addMessage(errorMsg, sessionId);
      const erroredSessions = await saveDesktopChatMessage(sessionId, errorMsg);
      setSessions(erroredSessions);
      const avatar = useAvatarState.getState();
      avatar.setEmotion('surprised');
      avatar.setActivityLabel('Backend issue');
      avatar.setLatestResponse(errorMsg.content);
      avatar.setResponsePreview(errorMsg.content);
    } finally {
      resetStream();
    }
  }, [
    activeSessionId,
    addMessage,
    createSession,
    flushDraft,
    isStreaming,
    metadata,
    resetStream,
    setDraft,
    setMetadata,
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

  const resetLocalChats = useCallback(async () => {
    if (isStreaming) return;
    const bootstrap = await resetAllDesktopChatSessions();
    resetStream();
    setBootstrap(bootstrap);
  }, [isStreaming, resetStream, setBootstrap]);

  return {
    sessions,
    activeSessionId,
    messages,
    draft,
    metadata,
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
    setSessionMetadata,
    startAgentConversation,
    resetLocalChats,
    persistAssistantMessage,
  };
}
