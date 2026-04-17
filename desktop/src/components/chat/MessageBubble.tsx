// NeuralClaw Desktop - Message Bubble

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage } from '../../lib/api';
import ToolCallCard from './ToolCallCard';

interface Props {
  message: ChatMessage;
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  const time = message.timestamp
    ? new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';
  const provenance = Array.isArray(message.metadata?.memoryProvenance)
    ? message.metadata?.memoryProvenance as Array<Record<string, unknown>>
    : [];
  const scopes = Array.isArray(message.metadata?.memoryScopes)
    ? message.metadata?.memoryScopes as string[]
    : [];
  const effectiveModel = typeof message.metadata?.effectiveModel === 'string'
    ? message.metadata.effectiveModel
    : '';
  const fallbackReason = typeof message.metadata?.fallbackReason === 'string'
    ? message.metadata.fallbackReason
    : '';

  return (
    <div className={`message-row ${isUser ? 'user' : 'assistant'}`}>
      <div className={`message-avatar ${isUser ? 'user' : 'bot'}`}>
        {isUser ? 'You' : 'NC'}
      </div>
      <div className={`message-stack ${isUser ? 'user' : 'assistant'}`}>
        <div className={`message-content ${isUser ? 'user' : 'bot'}`}>
          {isUser ? (
            <div className="message-plain-text">{message.content}</div>
          ) : (
            <>
              {message.tool_calls?.map((tc, index) => (
                <ToolCallCard key={index} toolCall={tc} />
              ))}
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
              {(provenance.length > 0 || scopes.length > 0 || effectiveModel || fallbackReason) && (
                <div className="message-memory-panel">
                  <div className="message-memory-topline">
                    {effectiveModel ? <span>Model {effectiveModel}</span> : null}
                    {scopes.length > 0 ? <span>Scopes {scopes.join(', ')}</span> : null}
                  </div>
                  {fallbackReason ? (
                    <div className="message-memory-reason">{fallbackReason}</div>
                  ) : null}
                  {provenance.length > 0 ? (
                    <div className="message-memory-list">
                      {provenance.slice(0, 4).map((item, index) => (
                        <div key={`${String(item.item_id || index)}`} className="message-memory-item">
                          <span className="message-memory-badge">{String(item.memory_type || 'memory')}</span>
                          <span className="message-memory-text">
                            {String(item.title || item.excerpt || 'Referenced memory')}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
            </>
          )}
        </div>
        {time && <div className="message-time">{time}</div>}
      </div>
    </div>
  );
}
