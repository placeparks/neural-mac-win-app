// NeuralClaw Desktop — Constants

// Dashboard (REST API — /health, /api/stats, /api/memory, etc.)
export const DASHBOARD_PORT = 8080;
export const DASHBOARD_BASE = `http://127.0.0.1:${DASHBOARD_PORT}`;

// Web Chat (WebSocket — /ws/chat)
export const WEBCHAT_PORT = 8099;
export const WEBCHAT_BASE = `http://127.0.0.1:${WEBCHAT_PORT}`;
export const WS_CHAT_URL = `ws://127.0.0.1:${WEBCHAT_PORT}/ws/chat`;

// Dashboard WebSocket for live traces
export const WS_TRACES_URL = `ws://127.0.0.1:${DASHBOARD_PORT}/ws/traces`;

export const HEALTH_POLL_INTERVAL = 5000;
export const WS_RECONNECT_INTERVAL = 3000;
export const WS_MAX_RECONNECT_INTERVAL = 30000; // backoff cap
export const WS_MAX_RECONNECT_ATTEMPTS = 10;    // soft cap before slowdown (no permanent give-up)

// Per-request timeouts (AbortController). Without these a hung gateway
// freezes the UI indefinitely.
export const API_HEALTH_TIMEOUT_MS = 3000;
export const API_DEFAULT_TIMEOUT_MS = 15000;
export const API_LONG_TIMEOUT_MS = 120000; // KB ingestion / generic model calls
// Chat completions may load a multi-GB local model on first call (Ollama cold
// start) and stream tokens slowly on consumer hardware. Allow up to 10 minutes
// before treating the gateway as stalled.
export const API_CHAT_TIMEOUT_MS = 600000;

export const APP_NAME = 'NeuralClaw';
export const APP_VERSION = import.meta.env.VITE_APP_VERSION || '0.0.0-dev';
export const APP_DESCRIPTION = 'The Self-Evolving AI Assistant';
