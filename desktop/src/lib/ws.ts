// NeuralClaw Desktop — WebSocket Manager
// Connects to /ws/chat on the web chat port for live messaging.
//
// Resilience contract:
//   * Reconnect with exponential backoff, capped at WS_MAX_RECONNECT_INTERVAL.
//   * Never permanently gives up — after the soft attempt cap it slows down
//     to the cap interval and keeps retrying so transient outages always heal.
//   * Emits a 'reconnected' event after a successful reconnect so the app
//     can re-sync state (chat sessions, tasks, agents) that may have changed
//     while the connection was down.
//   * Reports a 'reconnecting' status during retry windows so the UI can
//     surface it instead of silently lying about being connected.

import {
  WS_CHAT_URL,
  WS_RECONNECT_INTERVAL,
  WS_MAX_RECONNECT_INTERVAL,
  WS_MAX_RECONNECT_ATTEMPTS,
} from './constants';

export type WSEventType =
  | 'response'
  | 'response_delta'
  | 'response_complete'
  | 'status'
  | 'error'
  | 'reconnected'
  | 'bus';

export interface WSEvent {
  type: WSEventType;
  content?: string;
  delta?: string;
  confidence?: number;
  data?: unknown;
}

type WSListener = (event: WSEvent) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private listeners: Map<string, Set<WSListener>> = new Map();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connected = false;
  private _hasEverConnected = false;
  private _stopped = false;

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    this._stopped = false;
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return;
    }

    try {
      this.ws = new WebSocket(WS_CHAT_URL);

      this.ws.onopen = () => {
        const wasReconnect = this._hasEverConnected && this.reconnectAttempts > 0;
        this._connected = true;
        this._hasEverConnected = true;
        this.reconnectAttempts = 0;
        this.emit('status', { type: 'status', content: 'connected' });
        if (wasReconnect) {
          // Tell listeners they should re-sync state from the gateway.
          this.emit('reconnected', { type: 'reconnected', content: 'reconnected' });
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data) as WSEvent;
          this.emit(parsed.type, parsed);
          this.emit('*', parsed);
        } catch {
          // Non-JSON message
        }
      };

      this.ws.onclose = () => {
        this._connected = false;
        this.emit('status', { type: 'status', content: 'disconnected' });
        if (!this._stopped) this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this._connected = false;
        // onclose fires after onerror — schedule there to avoid double-retry.
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this._stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      // Clear handlers so close doesn't trigger reconnect.
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      try { this.ws.close(); } catch { /* ignore */ }
      this.ws = null;
    }
    this._connected = false;
  }

  on(event: string, listener: WSListener): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(listener);
    return () => this.listeners.get(event)?.delete(listener);
  }

  private emit(event: string, data: WSEvent): void {
    this.listeners.get(event)?.forEach((listener) => listener(data));
  }

  private scheduleReconnect(): void {
    if (this._stopped) return;
    if (this.reconnectTimer) return;

    this.reconnectAttempts++;
    // Exponential backoff: WS_RECONNECT_INTERVAL * 2^(attempts-1), capped.
    // After WS_MAX_RECONNECT_ATTEMPTS we stay at the cap and keep retrying
    // forever — transient gateway outages must always recover.
    const exp = Math.min(
      this.reconnectAttempts - 1,
      WS_MAX_RECONNECT_ATTEMPTS,
    );
    const delay = Math.min(
      WS_RECONNECT_INTERVAL * Math.pow(2, exp),
      WS_MAX_RECONNECT_INTERVAL,
    );

    this.emit('status', { type: 'status', content: 'reconnecting' });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  /** Send a chat message via WebSocket (matches WebChatAdapter protocol) */
  send(content: string): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ content }));
      return true;
    }
    return false;
  }
}

export const wsManager = new WebSocketManager();
