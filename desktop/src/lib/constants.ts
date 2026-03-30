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
export const WS_MAX_RECONNECT_ATTEMPTS = 10;

export const APP_NAME = 'NeuralClaw';
export const APP_VERSION = '1.0.0';
export const APP_DESCRIPTION = 'The Self-Evolving AI Assistant';
