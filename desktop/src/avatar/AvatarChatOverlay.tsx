import { FormEvent, useEffect, useState } from 'react';
import { useChat } from '../hooks/useChat';
import { useAvatarState } from './useAvatarState';

export default function AvatarChatOverlay() {
  const { latestResponse, inputOpen, setInputOpen } = useAvatarState();
  const { sendMessage, isStreaming } = useChat();
  const [text, setText] = useState('');
  const [bubbleVisible, setBubbleVisible] = useState(false);

  useEffect(() => {
    if (!latestResponse) return;
    setBubbleVisible(true);
    const timer = window.setTimeout(() => setBubbleVisible(false), 5000);
    return () => window.clearTimeout(timer);
  }, [latestResponse]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const content = text.trim();
    if (!content || isStreaming) return;
    await sendMessage(content);
    setText('');
    setInputOpen(false);
  };

  return (
    <div className="avatar-overlay">
      {bubbleVisible && latestResponse && (
        <div className="avatar-speech-bubble">
          {latestResponse}
        </div>
      )}

      {inputOpen ? (
        <form className="avatar-input-shell" onSubmit={(event) => void onSubmit(event)}>
          <input
            className="avatar-chat-input"
            autoFocus
            value={text}
            onChange={(event) => setText(event.target.value)}
            onBlur={() => {
              if (!text.trim()) setInputOpen(false);
            }}
            placeholder="Ask NeuralClaw..."
          />
          <button type="submit" className="avatar-chat-send" disabled={isStreaming || !text.trim()}>
            {isStreaming ? '...' : 'Send'}
          </button>
        </form>
      ) : (
        <button
          type="button"
          className="avatar-chat-toggle"
          onClick={() => setInputOpen(true)}
        >
          Ask
        </button>
      )}
    </div>
  );
}
