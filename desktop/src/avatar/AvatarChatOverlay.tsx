import { FormEvent, useEffect, useState } from 'react';
import { getChatBootstrap, saveDesktopChatDraft, saveDesktopChatMessage } from '../lib/api';
import { wsManager } from '../lib/ws';
import { useChatStore } from '../store/chatStore';
import { useAvatarState } from './useAvatarState';

export default function AvatarChatOverlay() {
  const { latestResponse, inputOpen, setInputOpen } = useAvatarState();
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
    if (!content) return;
    let activeSessionId: string | null = null;

    try {
      const bootstrap = await getChatBootstrap();
      activeSessionId = bootstrap.activeSessionId;
      const message = {
        role: 'user' as const,
        content,
        timestamp: new Date().toISOString(),
      };
      const chatStore = useChatStore.getState();
      chatStore.setBootstrap(bootstrap);
      chatStore.addMessage(message, bootstrap.activeSessionId);
      chatStore.setDraft('');
      chatStore.setPendingResponseSessionId(bootstrap.activeSessionId);
      chatStore.setStreaming(true);
      await saveDesktopChatDraft(bootstrap.activeSessionId, '');
      const sessions = await saveDesktopChatMessage(bootstrap.activeSessionId, message);
      chatStore.setSessions(sessions);
    } catch {
      // Keep avatar input responsive even if local persistence is unavailable.
    }

    if (!wsManager.connected) {
      if (activeSessionId) {
        const chatStore = useChatStore.getState();
        const errorMessage = {
          role: 'assistant' as const,
          content: 'Connection to the backend is unavailable. Start NeuralClaw and retry.',
          timestamp: new Date().toISOString(),
        };
        chatStore.addMessage(errorMessage, activeSessionId);
        const sessions = await saveDesktopChatMessage(activeSessionId, errorMessage).catch(() => null);
        if (sessions) chatStore.setSessions(sessions);
        chatStore.resetStream();
      }
      setText('');
      setInputOpen(false);
      return;
    }

    wsManager.send(content);
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
        <form className="avatar-input-shell" onSubmit={onSubmit}>
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
          <button type="submit" className="avatar-chat-send">Send</button>
        </form>
      ) : (
        <button
          type="button"
          className="avatar-chat-toggle"
          onClick={() => setInputOpen(true)}
        >
          Chat
        </button>
      )}
    </div>
  );
}
