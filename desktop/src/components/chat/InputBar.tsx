// NeuralClaw Desktop - Input Bar

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatAttachmentPayload, ModelOption } from '../../lib/api';
import { AUTONOMY_PROFILES, getAutonomyProfileByMode } from '../../lib/autonomy';

interface ProviderOption {
  id: string;
  label: string;
}

// Web Speech API types (not in lib.dom.d.ts by default)
interface ISpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onresult: ((e: ISpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

interface ISpeechRecognitionEvent {
  results: { 0: { transcript: string }; length: number }[];
}

declare global {
  interface Window {
    SpeechRecognition: new () => ISpeechRecognition;
    webkitSpeechRecognition: new () => ISpeechRecognition;
  }
}

function useSpeechRecognition(onResult: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const recogRef = useRef<ISpeechRecognition | null>(null);

  useEffect(() => {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    setSupported(Boolean(Ctor));
  }, []);

  const start = useCallback(() => {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) return;
    const recog = new Ctor();
    recog.continuous = false;
    recog.interimResults = false;
    recog.lang = 'en-US';
    recog.onresult = (e: ISpeechRecognitionEvent) => {
      const transcript = e.results[0]?.[0]?.transcript ?? '';
      if (transcript) onResult(transcript);
    };
    recog.onend = () => setListening(false);
    recog.onerror = () => setListening(false);
    recogRef.current = recog;
    recog.start();
    setListening(true);
  }, [onResult]);

  const stop = useCallback(() => {
    recogRef.current?.stop();
    setListening(false);
  }, []);

  return { listening, supported, start, stop };
}

interface Props {
  onSend: (message: string, attachments: ChatAttachmentPayload[]) => void;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  routeLabel?: string;
  providerOptions?: ProviderOption[];
  selectedProvider?: string | null;
  onProviderChange?: (provider: string) => void;
  modelOptions?: ModelOption[];
  selectedModel?: string | null;
  onModelChange?: (model: string) => void;
  modelsLoading?: boolean;
  teachingMode?: boolean | null;
  onTeachingModeChange?: (value: boolean) => void;
  autonomyMode?: string | null;
  onAutonomyModeChange?: (value: string) => void;
  attachmentSupportLabel?: string;
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
  providerOptions = [],
  selectedProvider,
  onProviderChange,
  modelOptions = [],
  selectedModel,
  onModelChange,
  modelsLoading = false,
  teachingMode,
  onTeachingModeChange,
  autonomyMode,
  onAutonomyModeChange,
  attachmentSupportLabel,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<ChatAttachmentPayload[]>([]);
  const activeAutonomyProfile = getAutonomyProfileByMode(autonomyMode);

  const handleVoiceResult = useCallback((transcript: string) => {
    onChange(value ? `${value} ${transcript}` : transcript);
  }, [value, onChange]);

  const { listening, supported: voiceSupported, start: startListening, stop: stopListening } = useSpeechRecognition(handleVoiceResult);

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
          {providerOptions.length > 0 && onProviderChange && (
            <select
              className="chat-model-select"
              value={selectedProvider || ''}
              onChange={(event) => onProviderChange(event.target.value)}
              disabled={disabled}
            >
              {providerOptions.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.label}
                </option>
              ))}
            </select>
          )}
          {(modelsLoading || modelOptions.length > 0) && onModelChange && (
            <select
              className="chat-model-select"
              value={selectedModel || ''}
              onChange={(event) => onModelChange(event.target.value)}
              disabled={disabled || modelsLoading}
            >
              {modelsLoading
                ? <option value="">Loading models…</option>
                : <option value="">Auto model</option>
              }
              {modelOptions.map((model) => (
                <option key={model.name} value={model.name}>
                  {model.icon} {model.name}
                </option>
              ))}
            </select>
          )}
          {onTeachingModeChange && (
            <label className="chat-attach-btn" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <input
                type="checkbox"
                checked={Boolean(teachingMode)}
                onChange={(event) => onTeachingModeChange(event.target.checked)}
                disabled={disabled}
              />
              Teach
            </label>
          )}
          {onAutonomyModeChange && (
            <select
              className="chat-model-select"
              value={autonomyMode || activeAutonomyProfile.mode}
              onChange={(event) => onAutonomyModeChange(event.target.value)}
              disabled={disabled}
              title={activeAutonomyProfile.description}
            >
              {AUTONOMY_PROFILES.map((profile) => (
                <option key={profile.id} value={profile.mode}>
                  {profile.label}
                </option>
              ))}
            </select>
          )}
          {voiceSupported && (
            <button
              type="button"
              className="chat-attach-btn"
              onClick={listening ? stopListening : startListening}
              disabled={disabled}
              title={listening ? 'Stop recording' : 'Voice input'}
              style={{ color: listening ? 'var(--accent-red, #f85149)' : undefined, position: 'relative' }}
            >
              {listening ? (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: 4, verticalAlign: 'middle' }}>
                    <rect x="6" y="6" width="12" height="12" rx="2" />
                  </svg>
                  Stop
                </>
              ) : (
                <>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 4, verticalAlign: 'middle' }}>
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                  </svg>
                  Voice
                </>
              )}
            </button>
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

      {attachmentSupportLabel ? (
        <div className="chat-session-subtitle" style={{ marginBottom: 8 }}>
          {attachmentSupportLabel}
        </div>
      ) : null}

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
