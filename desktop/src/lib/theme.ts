// NeuralClaw Desktop - Theme and Provider Colors

export const PROVIDER_COLORS = {
  openai: { bg: '#10a37f', text: '#ffffff', label: 'ChatGPT', icon: 'G' },
  anthropic: { bg: '#d4a27f', text: '#1a1a1a', label: 'Claude', icon: 'C' },
  google: { bg: '#4285f4', text: '#ffffff', label: 'Gemini', icon: 'G' },
  xai: { bg: '#1a1a1a', text: '#ffffff', label: 'Grok', icon: 'X' },
  meta: { bg: '#0668e1', text: '#ffffff', label: 'Llama', icon: 'M' },
  mistral: { bg: '#ff7000', text: '#ffffff', label: 'Mistral', icon: 'M' },
  venice: { bg: '#7c3aed', text: '#ffffff', label: 'Venice', icon: 'V' },
  minimax: { bg: '#0f766e', text: '#ffffff', label: 'MiniMax', icon: 'MM' },
  openrouter: { bg: '#6366f1', text: '#ffffff', label: 'OpenRouter', icon: 'R' },
  vercel: { bg: '#111111', text: '#ffffff', label: 'Vercel', icon: 'V' },
  local: { bg: '#6b7280', text: '#ffffff', label: 'Local (Ollama)', icon: 'L' },
} as const;

export type ProviderId = keyof typeof PROVIDER_COLORS;

export const PROVIDER_MAP: Record<string, ProviderId> = {
  ChatGPT: 'openai',
  Claude: 'anthropic',
  Gemini: 'google',
  Grok: 'xai',
  Llama: 'meta',
  Mistral: 'mistral',
  Venice: 'venice',
  MiniMax: 'minimax',
  OpenRouter: 'openrouter',
  Vercel: 'vercel',
  Local: 'local',
};

export const ALL_PROVIDERS: { id: ProviderId; name: string; company: string }[] = [
  { id: 'openai', name: 'ChatGPT', company: 'OpenAI' },
  { id: 'anthropic', name: 'Claude', company: 'Anthropic' },
  { id: 'google', name: 'Gemini', company: 'Google' },
  { id: 'xai', name: 'Grok', company: 'xAI' },
  { id: 'venice', name: 'Venice', company: 'Venice.ai' },
  { id: 'minimax', name: 'MiniMax', company: 'MiniMax' },
  { id: 'openrouter', name: 'OpenRouter', company: 'OpenRouter' },
  { id: 'vercel', name: 'Vercel', company: 'Vercel AI Gateway' },
  { id: 'meta', name: 'Llama', company: 'Meta' },
  { id: 'mistral', name: 'Mistral', company: 'Mistral AI' },
  { id: 'local', name: 'Local', company: 'Ollama' },
];

export const DEFAULT_MODELS: Record<ProviderId, { name: string; description: string; icon: string }[]> = {
  openai: [
    { name: 'gpt-5.4', description: 'Most capable GPT model', icon: 'G' },
    { name: 'gpt-4o', description: 'Powerful multimodal model', icon: '4' },
    { name: 'gpt-4o-mini', description: 'Fast and affordable', icon: 'F' },
    { name: 'gpt-nano', description: 'Ultra-fast edge model', icon: 'N' },
    { name: 'gpt-mini', description: 'Lightweight and efficient', icon: 'L' },
  ],
  anthropic: [
    { name: 'claude-opus-4-6', description: 'Most intelligent flagship', icon: 'O' },
    { name: 'claude-sonnet-4-6', description: 'Fast and capable', icon: 'S' },
    { name: 'claude-haiku-4-5', description: 'Ultra-fast and affordable', icon: 'H' },
    { name: 'claude-3-7-sonnet-latest', description: 'Reasoning-oriented Claude release', icon: '3' },
  ],
  google: [
    { name: 'gemini-2.5-pro', description: 'Google flagship', icon: 'P' },
    { name: 'gemini-2.5-flash', description: 'Fast and efficient', icon: 'F' },
  ],
  xai: [
    { name: 'grok-3', description: 'xAI flagship', icon: 'G' },
  ],
  venice: [
    { name: 'venice-large', description: 'Venice flagship reasoning model', icon: 'V' },
    { name: 'claude-sonnet-4-6', description: 'Claude via Venice proxy', icon: 'S' },
    { name: 'llama-3.3-70b', description: 'Open source via Venice', icon: 'L' },
  ],
  minimax: [
    { name: 'MiniMax-M1', description: 'MiniMax flagship reasoning model', icon: 'M1' },
    { name: 'MiniMax-Text-01', description: 'General-purpose MiniMax text model', icon: 'T' },
  ],
  openrouter: [
    { name: 'anthropic/claude-opus-4-6', description: 'Claude Opus via OpenRouter', icon: 'O' },
    { name: 'anthropic/claude-sonnet-4-6', description: 'Claude Sonnet via OpenRouter', icon: 'S' },
    { name: 'anthropic/claude-haiku-4-5', description: 'Claude Haiku via OpenRouter', icon: 'H' },
    { name: 'openai/gpt-5.4', description: 'GPT-5.4 via OpenRouter', icon: 'G' },
    { name: 'openai/gpt-4o', description: 'GPT-4o via OpenRouter', icon: '4' },
    { name: 'google/gemini-2.5-pro', description: 'Gemini via OpenRouter', icon: 'P' },
    { name: 'x-ai/grok-3-beta', description: 'Grok via OpenRouter', icon: 'X' },
  ],
  vercel: [
    { name: 'openai/gpt-5.4', description: 'GPT-5.4 through Vercel AI Gateway', icon: 'G' },
    { name: 'anthropic/claude-sonnet-4-6', description: 'Claude Sonnet via Vercel AI Gateway', icon: 'S' },
    { name: 'google/gemini-2.5-pro', description: 'Gemini via Vercel AI Gateway', icon: 'P' },
  ],
  meta: [
    { name: 'llama3.3:70b', description: 'Llama 3.3 via Ollama', icon: 'L' },
  ],
  mistral: [
    { name: 'mistral-large-latest', description: 'Mistral Large', icon: 'M' },
  ],
  // Local/Ollama models are fetched dynamically at runtime — do not hardcode here.
  local: [],
};
