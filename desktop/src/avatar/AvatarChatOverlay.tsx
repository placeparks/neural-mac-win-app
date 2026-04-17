import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useChat } from '../hooks/useChat';
import { useAvatarState } from './useAvatarState';

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

export default function AvatarChatOverlay() {
  const { latestResponse, inputOpen, setInputOpen } = useAvatarState();
  const { sendMessage, isStreaming } = useChat();
  const [text, setText] = useState('');
  const [bubbleVisible, setBubbleVisible] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<string | null>(null);
  const recognitionRef = useRef<ISpeechRecognition | null>(null);

  useEffect(() => {
    if (!latestResponse) return;
    setBubbleVisible(true);
    const timer = window.setTimeout(() => setBubbleVisible(false), 5000);
    return () => window.clearTimeout(timer);
  }, [latestResponse]);

  useEffect(() => {
    const win = window as typeof window & {
      SpeechRecognition?: new () => ISpeechRecognition;
      webkitSpeechRecognition?: new () => ISpeechRecognition;
    };
    setVoiceSupported(Boolean(win.SpeechRecognition || win.webkitSpeechRecognition));
  }, []);

  useEffect(() => () => {
    recognitionRef.current?.stop();
  }, []);

  const startListening = useCallback(async () => {
    const win = window as typeof window & {
      SpeechRecognition?: new () => ISpeechRecognition;
      webkitSpeechRecognition?: new () => ISpeechRecognition;
    };
    const Ctor = win.SpeechRecognition || win.webkitSpeechRecognition;
    if (!Ctor) {
      setVoiceSupported(false);
      setVoiceStatus('Speech recognition is not available in this desktop runtime yet.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
    } catch {
      setVoiceStatus('Microphone permission was denied. Allow mic access in Windows and try again.');
      return;
    }
    const recognition = new Ctor();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    let transcriptBuffer = '';
    let hadError = false;
    let stoppedManually = false;
    recognition.onresult = (event: ISpeechRecognitionEvent) => {
      const transcript = event.results[0]?.[0]?.transcript ?? '';
      if (transcript.trim()) {
        transcriptBuffer = transcript.trim();
        setText(transcriptBuffer);
        setVoiceStatus('Voice captured. Sending...');
      }
    };
    recognition.onend = () => {
      setListening(false);
      recognitionRef.current = null;
      if (hadError) return;
      if (stoppedManually) return;
      if (transcriptBuffer.trim()) {
        void (async () => {
          await sendMessage(transcriptBuffer.trim());
          setText('');
          setVoiceStatus(null);
          setInputOpen(false);
        })();
        return;
      }
      setVoiceStatus('No speech detected. Try again and speak right after the tone.');
    };
    recognition.onerror = () => {
      hadError = true;
      setListening(false);
      setVoiceStatus('Speech capture failed. Try again after checking microphone access.');
    };
    const originalStop = recognition.stop.bind(recognition);
    recognition.stop = () => {
      stoppedManually = true;
      originalStop();
    };
    recognitionRef.current = recognition;
    setVoiceStatus('Listening...');
    setInputOpen(true);
    recognition.start();
    setListening(true);
  }, [sendMessage, setInputOpen]);

  const toggleListening = useCallback(() => {
    if (isStreaming) return;
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      setVoiceStatus('Stopped listening.');
      return;
    }
    void startListening();
  }, [isStreaming, listening, startListening]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const content = text.trim();
    if (!content || isStreaming) return;
    await sendMessage(content);
    setText('');
    setVoiceStatus(null);
    setInputOpen(false);
  };

  return (
    <div className="avatar-overlay">
      {bubbleVisible && latestResponse && (
        <div className="avatar-speech-bubble">
          {latestResponse}
        </div>
      )}

      {voiceStatus ? (
        <div className={`avatar-voice-status${listening ? ' listening' : ''}`}>
          {voiceStatus}
        </div>
      ) : null}

      {inputOpen ? (
        <form className="avatar-input-shell" onSubmit={(event) => void onSubmit(event)}>
          <input
            className="avatar-chat-input"
            autoFocus
            value={text}
            onChange={(event) => setText(event.target.value)}
            onBlur={() => {
              if (!text.trim() && !listening) setInputOpen(false);
            }}
            placeholder="Ask NeuralClaw..."
          />
          {voiceSupported && (
            <button
              type="button"
              className={`avatar-chat-mic${listening ? ' listening' : ''}`}
              onClick={toggleListening}
              title={listening ? 'Stop listening' : 'Use voice input'}
            >
              {listening ? 'Stop' : 'Mic'}
            </button>
          )}
          <button type="submit" className="avatar-chat-send" disabled={isStreaming || !text.trim()}>
            {isStreaming ? '...' : 'Send'}
          </button>
        </form>
      ) : (
        <div className="avatar-action-row">
          <button
            type="button"
            className="avatar-chat-toggle"
            onClick={() => {
              setVoiceStatus(null);
              setInputOpen(true);
            }}
          >
            Ask
          </button>
          {voiceSupported ? (
            <button
              type="button"
              className={`avatar-chat-toggle avatar-chat-toggle-secondary${listening ? ' listening' : ''}`}
              onClick={toggleListening}
              disabled={isStreaming}
            >
              {listening ? 'Stop' : 'Talk'}
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}
