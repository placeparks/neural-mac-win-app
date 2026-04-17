import { getConfig } from './api';

interface VoiceAssistantRuntimeConfig {
  enabled: boolean;
  autoSpeak: boolean;
  voice: string;
  speed: number;
}

let cachedConfig: VoiceAssistantRuntimeConfig | null = null;
let cacheExpiresAt = 0;
let lastSpeechSignature = '';
let lastSpeechAt = 0;

function readVoiceConfig(raw: Record<string, unknown>): VoiceAssistantRuntimeConfig {
  const features = (raw.features as Record<string, unknown> | undefined) || {};
  const tts = (raw.tts as Record<string, unknown> | undefined) || {};
  return {
    enabled: Boolean(features.voice) && Boolean(tts.enabled),
    autoSpeak: Boolean(tts.auto_speak),
    voice: String(tts.voice || ''),
    speed: Number(tts.speed || 1),
  };
}

async function getVoiceRuntimeConfig(): Promise<VoiceAssistantRuntimeConfig> {
  const now = Date.now();
  if (cachedConfig && cacheExpiresAt > now) return cachedConfig;
  const config = await getConfig();
  cachedConfig = readVoiceConfig(config);
  cacheExpiresAt = now + 10000;
  return cachedConfig;
}

function matchVoice(requested: string, voices: SpeechSynthesisVoice[]) {
  const target = requested.trim().toLowerCase();
  if (!target) return null;
  return voices.find((voice) => {
    const name = voice.name.toLowerCase();
    const uri = voice.voiceURI.toLowerCase();
    return name === target || uri === target || name.includes(target) || uri.includes(target);
  }) || null;
}

export function invalidateVoiceAssistantCache() {
  cachedConfig = null;
  cacheExpiresAt = 0;
}

export function stopAssistantSpeech() {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
}

export async function maybeSpeakAssistantReply(text: string): Promise<boolean> {
  if (!text.trim()) return false;
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return false;

  const runtime = await getVoiceRuntimeConfig().catch(() => null);
  if (!runtime?.enabled || !runtime.autoSpeak) return false;

  const normalized = text.trim().replace(/\s+/g, ' ').slice(0, 320);
  const signature = `${normalized}|${runtime.voice}|${runtime.speed}`;
  const now = Date.now();
  if (signature === lastSpeechSignature && now - lastSpeechAt < 3500) {
    return false;
  }
  lastSpeechSignature = signature;
  lastSpeechAt = now;

  const synth = window.speechSynthesis;
  const utterance = new SpeechSynthesisUtterance(text.trim().slice(0, 900));
  utterance.rate = Math.min(2, Math.max(0.6, runtime.speed || 1));

  const play = () => {
    const voices = synth.getVoices();
    const match = matchVoice(runtime.voice, voices);
    if (match) utterance.voice = match;
    synth.cancel();
    synth.speak(utterance);
  };

  if (synth.getVoices().length > 0) {
    play();
    return true;
  }

  await new Promise<void>((resolve) => {
    const timeout = window.setTimeout(() => resolve(), 800);
    synth.onvoiceschanged = () => {
      window.clearTimeout(timeout);
      resolve();
    };
  });
  play();
  return true;
}
