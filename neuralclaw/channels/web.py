"""
Web Chat Channel Adapter — WebSocket-based browser chat.

Serves a minimal embedded chat UI and communicates via WebSocket.
Integrates as a standard channel adapter through the gateway pipeline.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage

try:
    from aiohttp import web
except ImportError:
    web = None  # type: ignore


# ---------------------------------------------------------------------------
# Embedded Chat UI
# ---------------------------------------------------------------------------

CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NeuralClaw Chat</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --user-bg: #1f3a5f; --agent-bg: #1a2332;
    --font: 'Segoe UI', system-ui, sans-serif;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font); background: var(--bg); color: var(--text);
    height: 100vh; display: flex; flex-direction: column; }
  .header { background: var(--surface); padding: 16px 24px;
    border-bottom: 1px solid var(--border); display: flex;
    align-items: center; gap: 12px; }
  .header h1 { font-size: 1.1rem; }
  .header h1 span { color: var(--accent); }
  .header .dot { width: 8px; height: 8px; border-radius: 50%;
    background: #3fb950; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
  .messages { flex: 1; overflow-y: auto; padding: 20px 24px; }
  .msg { max-width: 75%; margin-bottom: 12px; padding: 12px 16px;
    border-radius: 16px; font-size: 0.92rem; line-height: 1.5;
    word-wrap: break-word; white-space: pre-wrap; }
  .msg.user { margin-left: auto; background: var(--user-bg);
    border-bottom-right-radius: 4px; }
  .msg.agent { margin-right: auto; background: var(--agent-bg);
    border: 1px solid var(--border); border-bottom-left-radius: 4px; }
  .msg .meta { font-size: 0.72rem; color: var(--muted); margin-top: 6px; }
  .typing { padding: 12px 16px; color: var(--muted); font-size: 0.85rem;
    display: none; }
  .input-area { background: var(--surface); padding: 16px 24px;
    border-top: 1px solid var(--border); display: flex; gap: 12px; }
  .input-area input { flex: 1; background: var(--bg); border: 1px solid var(--border);
    border-radius: 24px; padding: 12px 20px; color: var(--text); font-size: 0.92rem;
    outline: none; transition: border-color 0.2s; }
  .input-area input:focus { border-color: var(--accent); }
  .input-area button { background: var(--accent); color: #fff; border: none;
    border-radius: 24px; padding: 12px 24px; font-size: 0.92rem; cursor: pointer;
    font-weight: 600; transition: opacity 0.2s; }
  .input-area button:hover { opacity: 0.85; }
  .input-area button:disabled { opacity: 0.4; cursor: default; }
</style>
</head>
<body>
<div class="header">
  <div class="dot"></div>
  <h1>Neural<span>Claw</span></h1>
</div>
<div class="messages" id="messages">
  <div class="msg agent">
    🧠 NeuralClaw is online. Send me a message to get started!
    <div class="meta">System</div>
  </div>
</div>
<div class="typing" id="typing">NeuralClaw is thinking...</div>
<div class="input-area">
  <input id="input" type="text" placeholder="Type a message..." autocomplete="off">
  <button id="send" onclick="sendMsg()">Send</button>
</div>
<script>
  const $ = id => document.getElementById(id);
  let ws;

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/chat`);
    ws.onopen = () => $('send').disabled = false;
    ws.onclose = () => {
      $('send').disabled = true;
      setTimeout(connect, 3000);
    };
    ws.onmessage = e => {
      const data = JSON.parse(e.data);
      if (data.type === 'response') {
        $('typing').style.display = 'none';
        addMsg(data.content, 'agent', data.confidence);
      }
    };
  }

  function addMsg(text, role, confidence) {
    const el = document.createElement('div');
    el.className = `msg ${role}`;
    let meta = role === 'user' ? 'You' : 'NeuralClaw';
    if (confidence !== undefined && role === 'agent')
      meta += ` · ${(confidence*100).toFixed(0)}% confidence`;
    el.innerHTML = text + `<div class="meta">${meta}</div>`;
    $('messages').appendChild(el);
    $('messages').scrollTop = $('messages').scrollHeight;
  }

  function sendMsg() {
    const input = $('input');
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== 1) return;
    addMsg(text, 'user');
    ws.send(JSON.stringify({ content: text }));
    input.value = '';
    $('typing').style.display = 'block';
  }

  $('input').addEventListener('keydown', e => {
    if (e.key === 'Enter') sendMsg();
  });
  connect();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# WebChat Adapter
# ---------------------------------------------------------------------------

class WebChatAdapter(ChannelAdapter):
    """
    WebSocket-based chat channel adapter.

    Serves a chat UI at /chat and communicates via WebSocket at /ws/chat.
    Integrates with the gateway pipeline like any other channel adapter.
    """

    name = "web"

    def __init__(self, host: str = "0.0.0.0", port: int = 8081) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._app: Any = None
        self._runner: Any = None
        self._ws_clients: dict[str, Any] = {}  # session_id -> ws

    async def start(self) -> None:
        """Start the web chat server."""
        if web is None:
            print("[WebChat] aiohttp not installed — web chat unavailable")
            return

        self._app = web.Application()
        self._app.router.add_get("/chat", self._handle_chat_page)
        self._app.router.add_get("/ws/chat", self._handle_ws)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        print(f"[WebChat] ✓ Chat UI at http://localhost:{self._port}/chat")

    async def stop(self) -> None:
        """Stop the web chat server."""
        for ws_client in self._ws_clients.values():
            await ws_client.close()
        if self._runner:
            await self._runner.cleanup()

    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a message back to the web client."""
        payload = {
            "type": "response",
            "content": content,
            "confidence": kwargs.get("confidence"),
        }

        # Primary: exact session lookup
        ws_client = self._ws_clients.get(channel_id)
        if ws_client is not None and not ws_client.closed:
            try:
                await ws_client.send_json(payload)
                return
            except Exception as e:
                print(f"[WebChat] Send error: {e}")

        # Fallback: send to any active WebSocket client
        for sid, ws in list(self._ws_clients.items()):
            if not ws.closed:
                try:
                    await ws.send_json(payload)
                    return
                except Exception:
                    continue

        print(f"[WebChat] No active WS client for response")

    async def _handle_chat_page(self, request: Any) -> Any:
        """Serve the embedded chat HTML."""
        return web.Response(text=CHAT_HTML, content_type="text/html")

    async def _handle_ws(self, request: Any) -> Any:
        """Handle WebSocket connections for chat."""
        ws_response = web.WebSocketResponse()
        await ws_response.prepare(request)

        session_id = uuid.uuid4().hex[:12]
        self._ws_clients[session_id] = ws_response

        try:
            async for raw_msg in ws_response:
                if raw_msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(raw_msg.data)
                        content = data.get("content", "")
                        if content:
                            msg = ChannelMessage(
                                content=content,
                                author_id=f"web_{session_id}",
                                author_name="Web User",
                                channel_id=session_id,
                                metadata={
                                    "platform": "web",
                                    "source": "web",
                                    "is_private": True,
                                    "is_shared": False,
                                },
                            )
                            await self._dispatch(msg)
                    except json.JSONDecodeError:
                        pass
        finally:
            self._ws_clients.pop(session_id, None)

        return ws_response
