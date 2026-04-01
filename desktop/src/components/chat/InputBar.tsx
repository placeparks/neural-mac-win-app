// NeuralClaw Desktop — Input Bar

import { useRef, useEffect } from 'react';

interface Props {
  onSend: (message: string) => void;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export default function InputBar({ onSend, value, onChange, disabled }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = '24px';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, [value]);

  const handleSend = () => {
    if (value.trim() && !disabled) {
      onSend(value.trim());
      if (textareaRef.current) textareaRef.current.style.height = '24px';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-input-area">
      <div className="chat-input-wrapper">
        <textarea
          ref={textareaRef}
          className="chat-input"
          placeholder="Message NeuralClaw..."
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
        />
        <button
          className="chat-send-btn"
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          aria-label="Send message"
        >
          {disabled ? <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> : '⬆'}
        </button>
      </div>
    </div>
  );
}
