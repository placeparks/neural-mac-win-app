// NeuralClaw Desktop - Chat View

import { useEffect, useRef, useState } from 'react';
import { getProviderDefaults, getProviderModels, type ModelOption } from '../../lib/api';
import { useChat } from '../../hooks/useChat';
import MessageBubble from './MessageBubble';
import InputBar from './InputBar';
import StatusBar from './StatusBar';

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
  const [localModels, setLocalModels] = useState<ModelOption[]>([]);
  const [localBaseUrl, setLocalBaseUrl] = useState('http://localhost:11434/v1');

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming, currentStreamContent]);

  useEffect(() => {
    let cancelled = false;
    void getProviderDefaults('local')
      .then((defaults) => {
        if (!cancelled && defaults.baseUrl.trim()) {
          setLocalBaseUrl(defaults.baseUrl.trim());
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const provider = metadata.selectedProvider || 'local';
    const baseUrl = metadata.baseUrl || localBaseUrl;
    if (!['local', 'meta'].includes(provider)) {
      setLocalModels([]);
      return;
    }

    let cancelled = false;
    getProviderModels(provider, baseUrl)
      .then((models) => {
        if (!cancelled) setLocalModels(models);
      })
      .catch(() => {
        if (!cancelled) setLocalModels([]);
      });

    return () => {
      cancelled = true;
    };
  }, [localBaseUrl, metadata.baseUrl, metadata.selectedProvider]);

  const routeParts = [
    metadata.targetAgent ? `Agent ${metadata.targetAgent}` : 'NeuralClaw',
    metadata.selectedModel
      ? (metadata.effectiveModel && metadata.effectiveModel !== metadata.selectedModel
        ? `${metadata.selectedModel} -> ${metadata.effectiveModel}`
        : metadata.selectedModel)
      : 'auto',
  ];
  const routeLabel = routeParts.join(' | ');

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
        <div className="chat-messages">
          {messages.length === 0 && !currentStreamContent ? (
            <div className="chat-empty">
              <span className="empty-icon">NC</span>
              <h2>NeuralClaw</h2>
              <p>
                Sessions persist locally. Use agent-bound sessions, switch local models, and attach docs or images from here.
              </p>
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
          modelOptions={localModels}
          selectedModel={metadata.selectedModel || ''}
          onModelChange={(model) => {
            void setSessionMetadata({
              ...metadata,
              selectedProvider: 'local',
              baseUrl: metadata.baseUrl || localBaseUrl,
              selectedModel: model || null,
            });
          }}
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
