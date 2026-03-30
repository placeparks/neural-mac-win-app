// NeuralClaw Desktop — Chat View (main chat interface)

import { useEffect, useRef } from 'react';
import { useChat } from '../../hooks/useChat';
import MessageBubble from './MessageBubble';
import InputBar from './InputBar';
import StatusBar from './StatusBar';

export default function ChatView() {
  const { messages, isStreaming, sendMessage, loadHistory, clearChatHistory } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <span className="empty-icon">🧠</span>
            <h2>NeuralClaw</h2>
            <p>
              Your AI assistant is ready. Type a message below to start a conversation.
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} />
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <InputBar onSend={sendMessage} disabled={isStreaming} />
      <StatusBar onClear={clearChatHistory} />
    </div>
  );
}
