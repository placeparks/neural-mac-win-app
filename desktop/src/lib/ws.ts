// NeuralClaw Desktop — WebSocket Manager
// Connects to /ws/chat on the web chat port for live messaging

import { WS_CHAT_URL, WS_RECONNECT_INTERVAL, WS_MAX_RECONNECT_ATTEMPTS } from './constants';

export type WSEventType = 'response' | 'response_delta' | 'response_complete' | 'status' | 'error';

export interface WSEvent {
  type: WSEventType;
  content?: string;
  delta?: string;
  confidence?: number;
}

type WSListener = (event: WSEvent) => void;

class WebSocketManager {
  private ws: WebSocket | null = null;
  private listeners: Map<string, Set<WSListener>> = new Map();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connected = false;

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    try {
      this.ws = new WebSocket(WS_CHAT_URL);

      this.ws.onopen = () => {
        this._connected = true;
        this.reconnectAttempts = 0;
        this.emit('status', { type: 'status', content: 'connected' });
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
        this.scheduleReconnect();
      };

      this.ws.onerror = () => {
        this._connected = false;
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempts = WS_MAX_RECONNECT_ATTEMPTS;
    this.ws?.close();
    this.ws = null;
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
    if (this.reconnectAttempts >= WS_MAX_RECONNECT_ATTEMPTS) return;
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, WS_RECONNECT_INTERVAL);
  }

  /** Send a chat message via WebSocket (matches WebChatAdapter protocol) */
  send(content: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ content }));
    }
  }
}

export const wsManager = new WebSocketManager();
