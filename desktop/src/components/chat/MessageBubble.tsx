// NeuralClaw Desktop — Message Bubble

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

  return (
    <div className={`message-row ${isUser ? 'user' : 'assistant'}`}>
      <div className={`message-avatar ${isUser ? 'user' : 'bot'}`}>
        {isUser ? '👤' : '🧠'}
      </div>
      <div>
        <div className={`message-content ${isUser ? 'user' : 'bot'}`}>
          {isUser ? (
            message.content
          ) : (
            <>
              {message.tool_calls?.map((tc, i) => (
                <ToolCallCard key={i} toolCall={tc} />
              ))}
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </>
          )}
        </div>
        {time && <div className="message-time">{time}</div>}
      </div>
    </div>
  );
}
