// NeuralClaw Desktop - Chat View

import { useEffect, useRef } from 'react';
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
  } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming, currentStreamContent]);

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
              <span className="empty-icon">🧠</span>
              <h2>NeuralClaw</h2>
              <p>
                Sessions now persist locally. Start a conversation and pick up where you left off later.
              </p>
            </div>
          ) : (
            <>
              {messages.map((msg, i) => (
                <MessageBubble key={`${msg.timestamp || i}-${msg.role}-${i}`} message={msg} />
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
          onSend={(message) => void sendMessage(message)}
          disabled={isStreaming}
        />
        <StatusBar onClear={() => void clearChatHistory()} sessionCount={sessions.length} />
      </div>
    </div>
  );
}
