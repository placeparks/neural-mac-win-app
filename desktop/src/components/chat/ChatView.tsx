// NeuralClaw Desktop - Chat View

import { useEffect, useMemo, useRef, useState } from 'react';
import { getProviderDefaults, getProviderModels, getProviderStatus, type ModelOption, type ProviderStatus } from '../../lib/api';
import { useChat } from '../../hooks/useChat';
import { ALL_PROVIDERS, PROVIDER_COLORS } from '../../lib/theme';
import MessageBubble from './MessageBubble';
import InputBar from './InputBar';
import StatusBar from './StatusBar';
import { getAutonomyProfileByMode } from '../../lib/autonomy';

function formatSessionTime(timestamp: number) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export default function ChatView() {
  const {
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
    resetLocalChats,
  } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [providerModels, setProviderModels] = useState<ModelOption[]>([]);
  const [providerModelsLoading, setProviderModelsLoading] = useState(false);
  const [providerStatuses, setProviderStatuses] = useState<ProviderStatus[]>([]);
  const [providerDefaults, setProviderDefaults] = useState<Record<string, string>>({});
  const primaryProvider = useMemo(
    () => providerStatuses.find((provider) => provider.is_primary)?.name || 'local',
    [providerStatuses],
  );
  const selectedProvider = metadata.selectedProvider || primaryProvider;
  const fallbackBaseUrl = providerDefaults[selectedProvider] || '';
  const effectiveBaseUrl = metadata.baseUrl?.trim() || fallbackBaseUrl;

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming, currentStreamContent]);

  useEffect(() => {
    let cancelled = false;
    void getProviderStatus()
      .then((status) => {
        if (!cancelled) {
          setProviderStatuses(status.providers || []);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void getProviderDefaults(selectedProvider)
      .then((defaults) => {
        if (!cancelled) {
          setProviderDefaults((current) => ({
            ...current,
            [selectedProvider]: defaults.baseUrl.trim(),
          }));
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [selectedProvider]);

  useEffect(() => {
    let cancelled = false;
    setProviderModelsLoading(true);
    getProviderModels(selectedProvider, effectiveBaseUrl)
      .then((models) => {
        if (!cancelled) {
          setProviderModels(models);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProviderModels([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setProviderModelsLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [effectiveBaseUrl, selectedProvider]);

  useEffect(() => {
    const storedBaseUrl = (metadata.baseUrl || '').trim();
    const resolvedBaseUrl = effectiveBaseUrl.trim();
    if (!resolvedBaseUrl || resolvedBaseUrl === storedBaseUrl) return;
    void setSessionMetadata({
      ...metadata,
      selectedProvider,
      baseUrl: resolvedBaseUrl,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveBaseUrl, selectedProvider]);

  const providerStatusMap = useMemo(
    () => new Map(providerStatuses.map((provider) => [provider.name, provider])),
    [providerStatuses],
  );

  const providerOptions = useMemo(
    () => {
      const visibleProviders = providerStatuses.length > 0
        ? ALL_PROVIDERS.filter((provider) => {
          const status = providerStatusMap.get(provider.id);
          return Boolean(
            provider.id === selectedProvider
            || (status && (status.available || status.configured || status.has_key)),
          );
        })
        : ALL_PROVIDERS;
      return visibleProviders.map((provider) => {
        const status = providerStatusMap.get(provider.id);
        let suffix = '';
        if (status?.available) suffix = 'Ready';
        else if (status?.has_key) suffix = 'Key set';
        else if (status?.configured) suffix = 'Configured';
        return {
          id: provider.id,
          label: suffix ? `${provider.name} - ${suffix}` : provider.name,
        };
      });
    },
    [providerStatusMap, providerStatuses.length, selectedProvider],
  );

  const providerLabel =
    PROVIDER_COLORS[selectedProvider as keyof typeof PROVIDER_COLORS]?.label || selectedProvider;
  const autonomyProfile = getAutonomyProfileByMode(metadata.autonomyMode || 'suggest-first');
  const selectedModelOption = providerModels.find((item) => item.name === (metadata.selectedModel || ''));
  const attachmentSupportLabel = selectedModelOption
    ? `Attachments: ${selectedModelOption.capabilities?.supportsVision ? 'images ok' : 'images may not work'}`
      + ` · ${selectedModelOption.capabilities?.supportsDocuments ? 'docs ok' : 'text docs only'}`
    : 'Attachments: images and text documents are supported when the selected model allows them.';

  const routeParts = [
    metadata.targetAgent ? `Agent ${metadata.targetAgent}` : 'NeuralClaw',
    providerLabel,
    metadata.teachingMode ? 'Teaching' : null,
    autonomyProfile.shortLabel,
    metadata.selectedModel
      ? (metadata.effectiveModel && metadata.effectiveModel !== metadata.selectedModel
        ? `${metadata.selectedModel} -> ${metadata.effectiveModel}`
        : metadata.selectedModel)
      : 'auto',
  ].filter(Boolean);
  const routeLabel = routeParts.join(' | ');
  const activeSession = sessions.find((session) => session.sessionId === activeSessionId) || null;

  return (
    <div className="chat-shell">
      <aside className="chat-session-rail">
        <div className="chat-session-rail-header">
          <div>
            <h2>Sessions</h2>
            <p>Persistent local chat history.</p>
          </div>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={isStreaming}
            onClick={() => void createSession()}
          >
            New
          </button>
        </div>

        <div className="chat-session-list">
          {!initialized ? (
            <div className="chat-session-empty">Loading sessions...</div>
          ) : sessions.length === 0 ? (
            <div className="chat-session-empty">No sessions yet.</div>
          ) : (
            sessions.map((session) => (
              <div
                key={session.sessionId}
                role="button"
                tabIndex={isStreaming ? -1 : 0}
                aria-disabled={isStreaming}
                className={`chat-session-card${session.sessionId === activeSessionId ? ' active' : ''}`}
                onClick={() => void switchSession(session.sessionId)}
                onKeyDown={(event) => {
                  if (isStreaming) return;
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    void switchSession(session.sessionId);
                  }
                }}
              >
                <div className="chat-session-card-top">
                  <span className="chat-session-title">{session.title}</span>
                  <span className="chat-session-time">{formatSessionTime(session.lastMessageAt)}</span>
                </div>
                {session.metadata?.targetAgent && (
                  <div className="chat-session-badge">Agent: {session.metadata.targetAgent}</div>
                )}
                {session.metadata?.selectedModel && (
                  <div className="chat-session-subtitle">
                    {session.metadata.effectiveModel && session.metadata.effectiveModel !== session.metadata.selectedModel
                      ? `${session.metadata.selectedModel} -> ${session.metadata.effectiveModel}`
                      : session.metadata.selectedModel}
                  </div>
                )}
                <div className="chat-session-preview">
                  {session.draft ? `Draft: ${session.draft}` : session.preview || 'No messages yet'}
                </div>
                <div className="chat-session-meta">
                  <span>{session.messageCount} msg</span>
                  <div className="chat-session-actions">
                    <span
                      role="button"
                      tabIndex={0}
                      className="chat-session-action"
                      onClick={(event) => {
                        event.stopPropagation();
                        const title = window.prompt('Rename session', session.title);
                        if (title && title.trim() && title.trim() !== session.title) {
                          void renameSession(session.sessionId, title.trim());
                        }
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          const title = window.prompt('Rename session', session.title);
                          if (title && title.trim() && title.trim() !== session.title) {
                            void renameSession(session.sessionId, title.trim());
                          }
                        }
                      }}
                    >
                      Rename
                    </span>
                    <span
                      role="button"
                      tabIndex={0}
                      className="chat-session-action danger"
                      onClick={(event) => {
                        event.stopPropagation();
                        if (window.confirm(`Delete "${session.title}"?`)) {
                          void deleteSession(session.sessionId);
                        }
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          if (window.confirm(`Delete "${session.title}"?`)) {
                            void deleteSession(session.sessionId);
                          }
                        }
                      }}
                    >
                      Delete
                    </span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>

      <div className="chat-container">
        <div className="chat-command-deck">
          <div>
            <div className="eyebrow">Active Route</div>
            <div className="chat-command-route">{routeLabel}</div>
            <div className="chat-command-copy">
              {activeSession
                ? `${activeSession.title} · ${activeSession.messageCount} messages`
                : 'Start a fresh session or resume one from the rail.'}
            </div>
          </div>
          <div className="chat-command-stats">
            <div className="chat-command-stat">
              <span>Sessions</span>
              <strong>{sessions.length}</strong>
            </div>
            <div className="chat-command-stat">
              <span>Provider</span>
              <strong>{providerLabel}</strong>
            </div>
            <div className="chat-command-stat">
              <span>Mode</span>
              <strong>{autonomyProfile.shortLabel}</strong>
            </div>
          </div>
        </div>

        <div className="chat-messages">
          {messages.length === 0 && !currentStreamContent ? (
            <div className="chat-empty">
              <span className="empty-icon">NC</span>
              <h2>NeuralClaw</h2>
              <p>
                Sessions persist locally. Use agent-bound sessions, switch providers and models, and attach docs or images from here.
              </p>
              <div className="chat-empty-grid">
                <div className="chat-empty-card">
                  <span>Persistent sessions</span>
                  <strong>{sessions.length}</strong>
                </div>
                <div className="chat-empty-card">
                  <span>Selected provider</span>
                  <strong>{providerLabel}</strong>
                </div>
                <div className="chat-empty-card">
                  <span>Teaching mode</span>
                  <strong>{metadata.teachingMode ? 'On' : 'Off'}</strong>
                </div>
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg, index) => (
                <MessageBubble key={`${msg.timestamp || index}-${msg.role}-${index}`} message={msg} />
              ))}
              {isStreaming && currentStreamContent && (
                <MessageBubble
                  message={{
                    role: 'assistant',
                    content: currentStreamContent,
                    timestamp: new Date().toISOString(),
                  }}
                />
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        <InputBar
          value={draft}
          onChange={updateDraft}
          onSend={(message, attachments) => void sendMessage(message, attachments)}
          disabled={isStreaming}
          routeLabel={routeLabel}
          providerOptions={providerOptions}
          selectedProvider={selectedProvider}
          onProviderChange={(provider) => {
            void (async () => {
              let nextBaseUrl = providerDefaults[provider] || '';
              if (!nextBaseUrl) {
                try {
                  const defaults = await getProviderDefaults(provider);
                  nextBaseUrl = defaults.baseUrl.trim();
                  if (nextBaseUrl) {
                    setProviderDefaults((current) => ({
                      ...current,
                      [provider]: nextBaseUrl,
                    }));
                  }
                } catch {
                  nextBaseUrl = '';
                }
              }
              await setSessionMetadata({
                ...metadata,
                selectedProvider: provider,
                baseUrl: nextBaseUrl,
                selectedModel: null,
                effectiveModel: null,
                fallbackReason: null,
              });
            })();
          }}
          modelOptions={providerModels}
          modelsLoading={providerModelsLoading}
          selectedModel={metadata.selectedModel || ''}
          onModelChange={(model) => {
            void setSessionMetadata({
              ...metadata,
              selectedProvider,
              baseUrl: effectiveBaseUrl,
              selectedModel: model || null,
              effectiveModel: null,
              fallbackReason: null,
            });
          }}
          teachingMode={metadata.teachingMode ?? false}
          onTeachingModeChange={(value) => {
            void setSessionMetadata({
              ...metadata,
              teachingMode: value,
            });
          }}
          autonomyMode={metadata.autonomyMode || 'suggest-first'}
          onAutonomyModeChange={(value) => {
            void setSessionMetadata({
              ...metadata,
              autonomyMode: value as NonNullable<typeof metadata.autonomyMode>,
            });
          }}
          attachmentSupportLabel={attachmentSupportLabel}
        />
        <StatusBar
          onClear={() => void clearChatHistory()}
          onResetAll={() => {
            if (window.confirm('Reset all local desktop chats and start fresh?')) {
              void resetLocalChats();
            }
          }}
          sessionCount={sessions.length}
        />
      </div>
    </div>
  );
}
