// NeuralClaw Desktop - Input Bar

import { useEffect, useRef, useState } from 'react';
import type { ChatAttachmentPayload, ModelOption } from '../../lib/api';

interface Props {
  onSend: (message: string, attachments: ChatAttachmentPayload[]) => void;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  routeLabel?: string;
  modelOptions?: ModelOption[];
  selectedModel?: string | null;
  onModelChange?: (model: string) => void;
}

const TEXT_MIME_TYPES = new Set([
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/json',
  'text/html',
  'application/xml',
  'text/xml',
]);

async function readAttachment(file: File): Promise<ChatAttachmentPayload | null> {
  if (file.type.startsWith('image/')) {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
      reader.readAsDataURL(file);
    });
    return {
      name: file.name,
      content: dataUrl,
      mimeType: file.type || 'image/png',
      kind: 'image',
    };
  }

  if (TEXT_MIME_TYPES.has(file.type) || file.type.startsWith('text/') || /\.(txt|md|csv|json|html?|xml)$/i.test(file.name)) {
    const text = await file.text();
    return {
      name: file.name,
      content: text,
      mimeType: file.type || 'text/plain',
      kind: 'document',
    };
  }

  return null;
}

export default function InputBar({
  onSend,
  value,
  onChange,
  disabled,
  routeLabel,
  modelOptions = [],
  selectedModel,
  onModelChange,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<ChatAttachmentPayload[]>([]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = '24px';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [value]);

  const handleSend = () => {
    if ((value.trim() || attachments.length) && !disabled) {
      onSend(value.trim(), attachments);
      setAttachments([]);
      if (fileInputRef.current) fileInputRef.current.value = '';
      if (textareaRef.current) textareaRef.current.style.height = '24px';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const next = await Promise.all(Array.from(files).map(readAttachment));
    setAttachments((current) => [...current, ...next.filter(Boolean) as ChatAttachmentPayload[]]);
  };

  return (
    <div className="chat-input-area">
      <div className="chat-input-toolbar">
        <div className="chat-input-route">{routeLabel || 'NeuralClaw chat'}</div>
        <div className="chat-input-controls">
          {modelOptions.length > 0 && onModelChange && (
            <select
              className="chat-model-select"
              value={selectedModel || ''}
              onChange={(event) => onModelChange(event.target.value)}
              disabled={disabled}
            >
              <option value="">Auto model</option>
              {modelOptions.map((model) => (
                <option key={model.name} value={model.name}>
                  {model.icon} {model.name}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            className="chat-attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
          >
            Attach
          </button>
        </div>
      </div>

      {attachments.length > 0 && (
        <div className="chat-attachment-strip">
          {attachments.map((item) => (
            <button
              key={`${item.kind}-${item.name}`}
              type="button"
              className="chat-attachment-chip"
              onClick={() => setAttachments((current) => current.filter((entry) => entry !== item))}
            >
              {item.name}
            </button>
          ))}
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        accept="image/*,.txt,.md,.markdown,.csv,.json,.html,.htm,.xml"
        onChange={(event) => {
          void handleFiles(event.target.files);
        }}
      />

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
          disabled={(!value.trim() && attachments.length === 0) || disabled}
          aria-label="Send message"
          type="button"
        >
          {disabled ? <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> : 'Send'}
        </button>
      </div>
    </div>
  );
}
