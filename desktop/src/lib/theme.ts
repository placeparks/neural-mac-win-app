// NeuralClaw Desktop - Theme and Provider Colors

export const PROVIDER_COLORS = {
  openai: { bg: '#10a37f', text: '#ffffff', label: 'ChatGPT', icon: 'G' },
  anthropic: { bg: '#d4a27f', text: '#1a1a1a', label: 'Claude', icon: 'C' },
  google: { bg: '#4285f4', text: '#ffffff', label: 'Gemini', icon: 'G' },
  xai: { bg: '#1a1a1a', text: '#ffffff', label: 'Grok', icon: 'X' },
  meta: { bg: '#0668e1', text: '#ffffff', label: 'Llama', icon: 'M' },
  mistral: { bg: '#ff7000', text: '#ffffff', label: 'Mistral', icon: 'M' },
  venice: { bg: '#7c3aed', text: '#ffffff', label: 'Venice', icon: 'V' },
  openrouter: { bg: '#6366f1', text: '#ffffff', label: 'OpenRouter', icon: 'R' },
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
  OpenRouter: 'openrouter',
  Local: 'local',
};

export const ALL_PROVIDERS: { id: ProviderId; name: string; company: string }[] = [
  { id: 'openai', name: 'ChatGPT', company: 'OpenAI' },
  { id: 'anthropic', name: 'Claude', company: 'Anthropic' },
  { id: 'google', name: 'Gemini', company: 'Google' },
  { id: 'xai', name: 'Grok', company: 'xAI' },
  { id: 'venice', name: 'Venice', company: 'Venice.ai' },
  { id: 'openrouter', name: 'OpenRouter', company: 'OpenRouter' },
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
  ],
  google: [
    { name: 'gemini-2.5-pro', description: 'Google flagship', icon: 'P' },
    { name: 'gemini-2.5-flash', description: 'Fast and efficient', icon: 'F' },
  ],
  xai: [
    { name: 'grok-3', description: 'xAI flagship', icon: 'G' },
  ],
  venice: [
    { name: 'claude-sonnet-4-6', description: 'Claude via Venice proxy', icon: 'S' },
    { name: 'llama-3.3-70b', description: 'Open source via Venice', icon: 'L' },
  ],
  openrouter: [
    { name: 'anthropic/claude-opus-4-6', description: 'Claude Opus via OpenRouter', icon: 'O' },
    { name: 'anthropic/claude-sonnet-4-6', description: 'Claude Sonnet via OpenRouter', icon: 'S' },
    { name: 'openai/gpt-5.4', description: 'GPT-5.4 via OpenRouter', icon: 'G' },
    { name: 'openai/gpt-4o', description: 'GPT-4o via OpenRouter', icon: '4' },
  ],
  meta: [
    { name: 'llama3.3:70b', description: 'Llama 3.3 via Ollama', icon: 'L' },
  ],
  mistral: [
    { name: 'mistral-large-latest', description: 'Mistral Large', icon: 'M' },
  ],
  local: [
    { name: 'qwen3.5:35b', description: 'Primary - deep reasoning and vision', icon: 'P' },
    { name: 'qwen3.5:9b', description: 'Fast - tool calls and skill dispatch', icon: 'F' },
    { name: 'qwen3.5:4b', description: 'Micro - intent routing and classification', icon: 'M' },
    { name: 'qwen3-embedding:8b', description: 'Embed - memory and RAG search', icon: 'E' },
  ],
};
