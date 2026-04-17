"""
Web Dashboard — Lightweight agent management dashboard.

Serves an embedded single-page dashboard for monitoring and controlling NeuralClaw:
- Reasoning trace timeline (live via WebSocket)
- Memory health stats + clear
- Swarm agent graph + spawn/despawn
- Federation node status + join peers
- Event bus log
- Feature toggles
- Send test messages through the cognitive pipeline
- API endpoints for programmatic access
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any
from urllib.parse import urlparse

from neuralclaw.config import load_config, update_config

try:
    from aiohttp import web
except ImportError:
    web = None  # type: ignore


if web is not None:
    @web.middleware
    async def _dashboard_security_middleware(request: Any, handler: Any) -> Any:
        dashboard = request.app.get("dashboard_instance")
        if dashboard is None:
            return web.json_response({"error": "Dashboard unavailable"}, status=503)
        if not dashboard._request_is_authorized(request):
            status = 401 if dashboard._auth_token else 403
            error = (
                "Dashboard access denied for non-local request."
                if dashboard._auth_token
                else "Dashboard is restricted to localhost unless a dashboard auth token is configured."
            )
            response = web.json_response({"error": error}, status=status)
            dashboard._apply_cors_headers(request, response)
            return response
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        dashboard._apply_cors_headers(request, response)
        return response


def _infer_model_capabilities(provider_name: str, model_id: str, raw: dict[str, Any]) -> dict[str, bool]:
    provider = (provider_name or "").strip().lower()
    model = (model_id or "").strip().lower()
    descriptor = " ".join(
        str(raw.get(key, "") or "").lower()
        for key in ("name", "family", "owned_by", "description")
    )
    haystack = f"{model} {descriptor}"

    supports_vision = False
    if provider in {"openai", "google", "xai"}:
        supports_vision = True
    elif provider == "anthropic":
        supports_vision = "claude" in haystack
    elif provider in {"openrouter", "venice", "mistral", "minimax", "proxy"}:
        supports_vision = any(token in haystack for token in (
            "vision", "vl", "gpt-4o", "gpt-4.1", "gpt-5", "gemini", "claude",
            "pixtral", "llava", "qwen-vl", "qwen2.5-vl", "minicpm-v", "gemma3",
        ))
    elif provider in {"local", "meta", "ollama"}:
        supports_vision = any(token in haystack for token in (
            "llava", "bakllava", "vision", "vl", "minicpm-v", "moondream",
            "qwen-vl", "qwen2.5-vl", "gemma3",
        ))

    return {
        "supports_tools": True,
        "supports_documents": True,
        "supports_vision": supports_vision,
    }


def _normalize_provider_model_catalog(provider_name: str, models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in models:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id", "") or raw.get("name", "") or "").strip()
        if not model_id:
            continue
        key = model_id.lower()
        if key in seen:
            continue
        seen.add(key)
        capabilities = _infer_model_capabilities(provider_name, model_id, raw)
        description = (
            str(raw.get("description", "") or "").strip()
            or str(raw.get("parameter_size", "") or "").strip()
            or str(raw.get("family", "") or "").strip()
            or str(raw.get("owned_by", "") or "").strip()
        )
        normalized.append({
            **raw,
            "id": model_id,
            "name": str(raw.get("name", "") or model_id).strip(),
            "description": description,
            "capabilities": capabilities,
            "supports_vision": capabilities["supports_vision"],
            "supports_documents": capabilities["supports_documents"],
            "supports_tools": capabilities["supports_tools"],
        })

    normalized.sort(key=lambda item: (str(item.get("name", "")).lower(), str(item.get("id", "")).lower()))
    return normalized


# ---------------------------------------------------------------------------
# Dashboard HTML (embedded — no external dependencies)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NeuralClaw Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --orange: #d29922;
    --purple: #bc8cff; --font: 'Segoe UI', system-ui, sans-serif;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--font); background: var(--bg); color: var(--text); }
  .header {
    background: linear-gradient(135deg, #1a1e2e 0%, #0d1117 100%);
    padding: 20px 32px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
  }
  .header h1 { font-size: 1.4rem; }
  .header h1 span { color: var(--accent); }
  .status-dot { display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; background: var(--green); margin-right: 8px;
    animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
    padding: 24px 32px; max-width: 1400px; }
  .grid-cont { padding-top: 0; }
  .card { background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px; }
  .card h2 { font-size: 0.85rem; text-transform: uppercase;
    color: var(--muted); margin-bottom: 12px; letter-spacing: 0.05em; }
  .stat-row { display: flex; justify-content: space-between;
    padding: 8px 0; border-bottom: 1px solid var(--border); }
  .stat-row:last-child { border-bottom: none; }
  .stat-label { color: var(--muted); }
  .stat-value { font-weight: 600; }
  .stat-value.good { color: var(--green); }
  .stat-value.warn { color: var(--orange); }
  .stat-value.bad { color: var(--red); }
  .trace-list { max-height: 400px; overflow-y: auto; font-size: 0.82rem; }
  .trace { padding: 8px 12px; border-left: 3px solid var(--border);
    margin-bottom: 4px; background: rgba(255,255,255,0.02); border-radius: 0 6px 6px 0; }
  .trace.perception { border-color: var(--accent); }
  .trace.memory { border-color: var(--purple); }
  .trace.reasoning { border-color: var(--green); }
  .trace.action { border-color: var(--orange); }
  .trace.swarm { border-color: var(--red); }
  .trace .ts { color: var(--muted); font-size: 0.75rem; }
  .agent-chip { display: inline-block; padding: 4px 10px; margin: 4px;
    border-radius: 16px; font-size: 0.8rem; border: 1px solid var(--border); }
  .agent-chip.online { border-color: var(--green); color: var(--green); }
  .agent-chip.offline { border-color: var(--muted); color: var(--muted); }
  .agent-chip .x-btn { background: none; border: none; color: var(--red);
    cursor: pointer; padding: 0 0 0 5px; font-size: 0.85rem; opacity: 0.6; }
  .agent-chip .x-btn:hover { opacity: 1; }
  .full-width { grid-column: 1 / -1; }
  #connection { font-size: 0.75rem; color: var(--muted); }

  /* Federation panel */
  .fed-table { width: 100%; font-size: 0.82rem; border-collapse: collapse; }
  .fed-table th { text-align: left; color: var(--muted); font-weight: 500;
    padding: 6px 8px; border-bottom: 1px solid var(--border); font-size: 0.75rem;
    text-transform: uppercase; letter-spacing: 0.04em; }
  .fed-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
  .trust-bar { display: inline-block; height: 6px; border-radius: 3px;
    min-width: 8px; vertical-align: middle; }
  .trust-val { font-size: 0.75rem; color: var(--muted); margin-left: 6px; }
  .node-status { font-size: 0.75rem; padding: 2px 8px; border-radius: 8px;
    font-weight: 600; text-transform: uppercase; }
  .node-status.online { background: rgba(63,185,80,0.15); color: var(--green); }
  .node-status.offline { background: rgba(139,148,158,0.15); color: var(--muted); }
  .node-status.degraded { background: rgba(210,153,34,0.15); color: var(--orange); }
  .node-status.untrusted { background: rgba(248,81,73,0.15); color: var(--red); }

  /* Filter bar */
  .filter-bar { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
  .filter-btn { background: transparent; border: 1px solid var(--border); color: var(--muted);
    padding: 4px 12px; border-radius: 14px; font-size: 0.75rem; cursor: pointer;
    font-family: var(--font); transition: all 0.15s; }
  .filter-btn:hover { border-color: var(--accent); color: var(--accent); }
  .filter-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  /* Bus event log */
  .bus-list { max-height: 300px; overflow-y: auto; font-size: 0.8rem; }
  .bus-event { padding: 6px 10px; border-bottom: 1px solid var(--border);
    display: flex; gap: 10px; align-items: baseline; }
  .bus-event .ev-ts { color: var(--muted); font-size: 0.72rem; white-space: nowrap; }
  .bus-event .ev-type { font-weight: 600; font-size: 0.75rem; padding: 1px 6px;
    border-radius: 4px; white-space: nowrap; }
  .bus-event .ev-type.perception { background: rgba(88,166,255,0.15); color: var(--accent); }
  .bus-event .ev-type.memory { background: rgba(188,140,255,0.15); color: var(--purple); }
  .bus-event .ev-type.reasoning { background: rgba(63,185,80,0.15); color: var(--green); }
  .bus-event .ev-type.action { background: rgba(210,153,34,0.15); color: var(--orange); }
  .bus-event .ev-type.error { background: rgba(248,81,73,0.15); color: var(--red); }
  .bus-event .ev-type.swarm { background: rgba(248,81,73,0.1); color: var(--red); }
  .bus-event .ev-type.default { background: rgba(139,148,158,0.15); color: var(--muted); }
  .bus-event .ev-src { color: var(--muted); font-size: 0.72rem; }
  .bus-event .ev-data { color: var(--text); flex: 1; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .fed-count { font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; }

  /* Action UI */
  .btn { padding: 6px 14px; border-radius: 8px; font-size: 0.8rem;
    cursor: pointer; font-family: var(--font); border: 1px solid; transition: opacity 0.15s; }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn-danger { background: transparent; color: var(--red); border-color: var(--red); }
  .btn-sm { padding: 3px 8px; font-size: 0.75rem; border-radius: 6px; }
  .action-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .input-row { display: flex; gap: 8px; margin-top: 10px; }
  .txt { background: var(--bg); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 6px 10px; font-family: var(--font);
    font-size: 0.82rem; flex: 1; min-width: 120px; }
  .txt:focus { outline: none; border-color: var(--accent); }

  /* Modal */
  .modal-overlay { display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.6); z-index: 100; align-items: center; justify-content: center; }
  .modal-overlay.open { display: flex; }
  .modal { background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 28px; min-width: 360px; max-width: 480px; width: 90%; }
  .modal h3 { font-size: 1rem; margin-bottom: 16px; }
  .modal label { display: block; font-size: 0.78rem; color: var(--muted);
    margin-bottom: 4px; margin-top: 10px; }
  .modal label:first-of-type { margin-top: 0; }
  .modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }

  /* Toast */
  .toast { position: fixed; bottom: 24px; right: 24px; background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px;
    font-size: 0.82rem; z-index: 200; opacity: 0; transition: opacity 0.2s;
    max-width: 360px; pointer-events: none; }
  .toast.show { opacity: 1; }
  .toast.ok { border-color: var(--green); color: var(--green); }
  .toast.err { border-color: var(--red); color: var(--red); }

  /* Feature toggles */
  .toggle-section { margin-top: 14px; }
  .toggle-header { font-size: 0.75rem; text-transform: uppercase; color: var(--muted);
    letter-spacing: 0.05em; margin-bottom: 8px; }
  .toggle-row { display: flex; justify-content: space-between; align-items: center;
    padding: 6px 0; border-bottom: 1px solid var(--border); }
  .toggle-row:last-child { border-bottom: none; }
  .toggle-label { font-size: 0.82rem; }
  .restart-note { font-size: 0.68rem; color: var(--orange); margin-left: 6px; }
  .toggle { position: relative; display: inline-block; width: 36px; height: 20px; }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle-slider { position: absolute; inset: 0; background: var(--border);
    border-radius: 20px; cursor: pointer; transition: background 0.2s; }
  .toggle-slider:before { content: ''; position: absolute; height: 14px; width: 14px;
    left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: transform 0.2s; }
  .toggle input:checked + .toggle-slider { background: var(--accent); }
  .toggle input:checked + .toggle-slider:before { transform: translateX(16px); }

  /* Message response */
  .msg-resp { margin-top: 10px; padding: 10px 12px; background: rgba(88,166,255,0.06);
    border: 1px solid rgba(88,166,255,0.2); border-radius: 8px; font-size: 0.82rem;
    white-space: pre-wrap; display: none; max-height: 200px; overflow-y: auto; }
</style>
</head>
<body>
<div class="header">
  <h1><span class="status-dot"></span>Neural<span>Claw</span> Dashboard</h1>
  <span id="connection">Connecting...</span>
</div>
<div class="grid">
  <!-- System Status + Feature Toggles -->
  <div class="card">
    <h2>System Status</h2>
    <div id="stats">Loading...</div>
    <div class="toggle-section">
      <div class="toggle-header">Feature Toggles</div>
      <div id="feature-toggles">Loading...</div>
    </div>
  </div>
  <!-- Swarm Agents + Spawn -->
  <div class="card">
    <h2>Swarm Agents</h2>
    <div id="agents">No agents registered</div>
    <div class="action-row">
      <button class="btn btn-primary btn-sm" onclick="openSpawnModal()">+ Spawn Agent</button>
    </div>
  </div>
  <!-- Federation Nodes + Join -->
  <div class="card">
    <h2>Federation Nodes</h2>
    <div id="federation">No federation data</div>
    <div class="input-row">
      <input id="fed-ep" class="txt" placeholder="http://peer:8100" type="url">
      <button class="btn btn-primary btn-sm" onclick="joinFederation()">Join</button>
    </div>
  </div>
  <!-- Memory Health + Clear -->
  <div class="card">
    <h2>Memory Health</h2>
    <div id="memory">Loading...</div>
    <div class="action-row">
      <button class="btn btn-danger btn-sm" onclick="clearMemory()">Clear All Memory</button>
    </div>
  </div>
  <!-- Send Test Message -->
  <div class="card full-width">
    <h2>Send Test Message</h2>
    <div style="display:flex;gap:8px">
      <input id="msg-in" class="txt" placeholder="Type a message to test the cognitive pipeline..."
        onkeydown="if(event.key==='Enter')sendMessage()">
      <button class="btn btn-primary" id="msg-btn" onclick="sendMessage()">Send</button>
    </div>
    <div id="msg-resp" class="msg-resp"></div>
  </div>
  <!-- Live Traces -->
  <div class="card full-width">
    <h2>Live Reasoning Traces</h2>
    <div class="filter-bar">
      <button class="filter-btn active" onclick="filterTraces('all')">All</button>
      <button class="filter-btn" onclick="filterTraces('perception')">Perception</button>
      <button class="filter-btn" onclick="filterTraces('memory')">Memory</button>
      <button class="filter-btn" onclick="filterTraces('reasoning')">Reasoning</button>
      <button class="filter-btn" onclick="filterTraces('action')">Action</button>
      <button class="filter-btn" onclick="filterTraces('swarm')">Swarm</button>
    </div>
    <div id="traces" class="trace-list"></div>
  </div>
  <!-- Event Bus Log -->
  <div class="card full-width">
    <h2>Event Bus Log</h2>
    <div id="bus" class="bus-list">No events yet</div>
  </div>
</div>

<!-- Spawn Agent Modal -->
<div id="spawn-modal" class="modal-overlay" onclick="if(event.target===this)closeSpawnModal()">
  <div class="modal">
    <h3>Spawn Remote Agent</h3>
    <label>Name</label>
    <input id="sp-name" class="txt" style="width:100%" placeholder="my-agent">
    <label>Description</label>
    <input id="sp-desc" class="txt" style="width:100%" placeholder="What this agent does">
    <label>Capabilities (comma-separated)</label>
    <input id="sp-caps" class="txt" style="width:100%" placeholder="research, analysis">
    <label>Endpoint URL</label>
    <input id="sp-ep" class="txt" style="width:100%" placeholder="http://host:8100">
    <div class="modal-actions">
      <button class="btn" style="border-color:var(--border);color:var(--muted)" onclick="closeSpawnModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitSpawn()">Spawn</button>
    </div>
  </div>
</div>

<!-- Toast -->
<div id="toast" class="toast"></div>

<script>
  const $ = id => document.getElementById(id);
  let ws, activeFilter = 'all';

  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function toast(msg, ok) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'toast show ' + (ok ? 'ok' : 'err');
    clearTimeout(t._tid);
    t._tid = setTimeout(() => t.classList.remove('show'), 3500);
  }

  // ---- WebSocket ----
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/traces`);
    ws.onopen = () => { $('connection').textContent = 'Connected'; };
    ws.onclose = () => {
      $('connection').textContent = 'Disconnected — reconnecting...';
      setTimeout(connect, 3000);
    };
    ws.onmessage = e => {
      const data = JSON.parse(e.data);
      if (data.type === 'trace') addTrace(data);
      else if (data.type === 'stats') updateStats(data);
      else if (data.type === 'agents') updateAgents(data);
      else if (data.type === 'federation') updateFederation(data);
      else if (data.type === 'memory') updateMemory(data);
      else if (data.type === 'bus') updateBus(data);
    };
  }

  // ---- Traces ----
  function addTrace(t) {
    const el = document.createElement('div');
    const cat = (t.category || 'action').toLowerCase();
    el.className = `trace ${cat}`;
    el.setAttribute('data-cat', cat);
    el.innerHTML = `<span class="ts">${new Date(t.timestamp*1000).toLocaleTimeString()}</span>
      &nbsp;[${(t.category||'').toUpperCase()}] ${esc(t.message || '')}`;
    if (activeFilter !== 'all' && cat !== activeFilter) el.style.display = 'none';
    $('traces').prepend(el);
    if ($('traces').children.length > 200)
      $('traces').removeChild($('traces').lastChild);
  }

  function filterTraces(cat) {
    activeFilter = cat;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    document.querySelectorAll('#traces .trace').forEach(el => {
      el.style.display = (cat === 'all' || el.getAttribute('data-cat') === cat) ? '' : 'none';
    });
  }

  // ---- Panel updaters ----
  function updateStats(s) {
    const d = s.data || {};
    const rate = d.success_rate || 0;
    const cls = rate > 0.8 ? 'good' : rate > 0.5 ? 'warn' : 'bad';
    $('stats').innerHTML = `
      <div class="stat-row"><span class="stat-label">Provider</span>
        <span class="stat-value">${esc(d.provider||'--')}</span></div>
      <div class="stat-row"><span class="stat-label">Interactions</span>
        <span class="stat-value">${d.interactions||0}</span></div>
      <div class="stat-row"><span class="stat-label">Success Rate</span>
        <span class="stat-value ${cls}">${(rate*100).toFixed(0)}%</span></div>
      <div class="stat-row"><span class="stat-label">Skills Loaded</span>
        <span class="stat-value">${d.skills||0}</span></div>
      <div class="stat-row"><span class="stat-label">Channels</span>
        <span class="stat-value">${esc(d.channels||'--')}</span></div>
      <div class="stat-row"><span class="stat-label">Uptime</span>
        <span class="stat-value">${esc(d.uptime||'--')}</span></div>
    `;
  }

  function updateAgents(a) {
    const agents = a.data || [];
    if (!agents.length) { $('agents').textContent = 'No agents on mesh'; return; }
    $('agents').innerHTML = agents.map(ag =>
      `<span class="agent-chip ${(ag.status||'online').toLowerCase()}">${esc(ag.name)}` +
      `${(ag.capabilities||[]).length ? ' (' + esc((ag.capabilities||[]).join(', ')) + ')' : ''}` +
      `<button class="x-btn" onclick="despawnAgent('${esc(ag.name)}')" title="Despawn">x</button></span>`
    ).join('');
  }

  function updateFederation(f) {
    const d = f.data || {};
    const nodes = d.nodes || [];
    if (!nodes.length) {
      $('federation').innerHTML = '<span style="color:var(--muted)">No federation peers connected</span>';
      return;
    }
    let html = `<div class="fed-count">${d.online_nodes||0} online / ${d.total_nodes||0} total</div>`;
    html += '<table class="fed-table"><tr><th>Name</th><th>Status</th><th>Trust</th><th>Capabilities</th><th></th></tr>';
    for (const n of nodes) {
      const trust = (n.trust_score || 0);
      const pct = Math.round(trust * 100);
      const color = trust > 0.7 ? 'var(--green)' : trust > 0.4 ? 'var(--orange)' : 'var(--red)';
      const st = (n.status || 'offline').toLowerCase();
      html += `<tr>
        <td>${esc(n.name)}</td>
        <td><span class="node-status ${st}">${st}</span></td>
        <td><span class="trust-bar" style="width:${pct}px;background:${color}"></span><span class="trust-val">${pct}%</span></td>
        <td style="color:var(--muted);font-size:0.75rem">${(n.capabilities||[]).join(', ')||'--'}</td>
        <td><button class="btn btn-primary btn-sm" onclick="openMsgPeer('${esc(n.name)}')" ${st!=='online'?'disabled':''}>Message</button></td>
      </tr>`;
    }
    html += '</table>';
    html += '<div id="peer-msg-area" style="display:none;margin-top:10px">';
    html += '<div style="font-size:0.78rem;color:var(--muted);margin-bottom:4px">Message <strong id="peer-target"></strong></div>';
    html += '<div style="display:flex;gap:8px"><input id="peer-msg-in" class="txt" placeholder="Ask the peer agent..." onkeydown="if(event.key===\\'Enter\\')sendPeerMsg()">';
    html += '<button class="btn btn-primary btn-sm" id="peer-msg-btn" onclick="sendPeerMsg()">Send</button></div>';
    html += '<div id="peer-msg-resp" class="msg-resp"></div></div>';
    $('federation').innerHTML = html;
  }

  function updateMemory(m) {
    const d = m.data || {};
    $('memory').innerHTML = `
      <div class="stat-row"><span class="stat-label">Episodic Episodes</span>
        <span class="stat-value">${d.episodic_count||0}</span></div>
      <div class="stat-row"><span class="stat-label">Semantic Entities</span>
        <span class="stat-value">${d.semantic_count||0}</span></div>
      <div class="stat-row"><span class="stat-label">Procedures</span>
        <span class="stat-value">${d.procedural_count||0}</span></div>
    `;
  }

  function updateBus(b) {
    const events = b.data || [];
    if (!events.length) { $('bus').innerHTML = '<span style="color:var(--muted)">No events yet</span>'; return; }
    $('bus').innerHTML = events.map(ev => {
      const typeLow = (ev.type || '').toLowerCase();
      let cls = 'default';
      if (typeLow.includes('percep') || typeLow.includes('signal') || typeLow.includes('intent')) cls = 'perception';
      else if (typeLow.includes('memory') || typeLow.includes('retriev')) cls = 'memory';
      else if (typeLow.includes('reason') || typeLow.includes('fast') || typeLow.includes('reflect')) cls = 'reasoning';
      else if (typeLow.includes('action') || typeLow.includes('tool') || typeLow.includes('skill') || typeLow.includes('response')) cls = 'action';
      else if (typeLow.includes('error')) cls = 'error';
      else if (typeLow.includes('swarm') || typeLow.includes('delegat') || typeLow.includes('mesh') || typeLow.includes('feder')) cls = 'swarm';
      const ts = ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : '';
      return `<div class="bus-event">
        <span class="ev-ts">${ts}</span>
        <span class="ev-type ${cls}">${esc(ev.type||'?')}</span>
        <span class="ev-src">${esc(ev.source||'')}</span>
        <span class="ev-data">${esc(ev.data_preview||'')}</span>
      </div>`;
    }).join('');
  }

  // ---- Feature toggles ----
  async function loadFeatures() {
    try {
      const r = await fetch('/api/features');
      if (!r.ok) return;
      renderFeatures(await r.json());
    } catch(e) {}
  }
  function renderFeatures(features) {
    const el = $('feature-toggles');
    if (!Object.keys(features).length) {
      el.innerHTML = '<span style="color:var(--muted);font-size:0.8rem">Not available</span>';
      return;
    }
    el.innerHTML = Object.entries(features).map(([key, m]) => `
      <div class="toggle-row">
        <span class="toggle-label">${esc(m.label||key)}${m.live ? '' : '<span class="restart-note">(restart)</span>'}</span>
        <label class="toggle">
          <input type="checkbox" ${m.value ? 'checked' : ''} onchange="setFeature('${esc(key)}',this.checked)">
          <span class="toggle-slider"></span>
        </label>
      </div>
    `).join('');
  }
  async function setFeature(feature, value) {
    try {
      const r = await fetch('/api/features', {method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({feature, value})});
      const d = await r.json();
      if (d.ok) toast(`${feature} ${value?'enabled':'disabled'}`, true);
      else { toast(d.error||'Toggle failed', false); loadFeatures(); }
    } catch(e) { toast('Network error', false); loadFeatures(); }
  }

  // ---- Spawn agent ----
  function openSpawnModal() { $('spawn-modal').classList.add('open'); $('sp-name').focus(); }
  function closeSpawnModal() {
    $('spawn-modal').classList.remove('open');
    ['sp-name','sp-desc','sp-caps','sp-ep'].forEach(id => $(id).value = '');
  }
  async function submitSpawn() {
    const name = $('sp-name').value.trim();
    const description = $('sp-desc').value.trim();
    const capabilities = $('sp-caps').value.trim();
    const endpoint = $('sp-ep').value.trim();
    if (!name || !endpoint) { toast('Name and endpoint are required', false); return; }
    try {
      const r = await fetch('/api/spawn', {method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name, description, capabilities, endpoint})});
      const d = await r.json();
      if (d.ok) {
        toast(`Agent "${name}" spawned`, true);
        closeSpawnModal();
        fetch('/api/agents').then(r=>r.json()).then(d=>updateAgents({data:d})).catch(()=>{});
      } else toast(d.error||'Spawn failed', false);
    } catch(e) { toast('Network error', false); }
  }

  // ---- Despawn ----
  async function despawnAgent(name) {
    if (!confirm('Despawn agent "' + name + '"?')) return;
    try {
      const r = await fetch('/api/despawn', {method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name})});
      const d = await r.json();
      if (d.ok) {
        toast(`Agent "${name}" despawned`, true);
        fetch('/api/agents').then(r=>r.json()).then(d=>updateAgents({data:d})).catch(()=>{});
      } else toast(d.error||'Despawn failed', false);
    } catch(e) { toast('Network error', false); }
  }

  // ---- Send message ----
  async function sendMessage() {
    const content = $('msg-in').value.trim();
    if (!content) return;
    const btn = $('msg-btn'), resp = $('msg-resp');
    btn.disabled = true; btn.textContent = 'Sending...'; resp.style.display = 'none';
    try {
      const r = await fetch('/api/message', {method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({content})});
      const d = await r.json();
      if (d.ok) { resp.textContent = d.response; resp.style.display = 'block'; $('msg-in').value = ''; }
      else toast(d.error||'Message failed', false);
    } catch(e) { toast('Network error', false); }
    finally { btn.disabled = false; btn.textContent = 'Send'; }
  }

  // ---- Join federation ----
  async function joinFederation() {
    const endpoint = $('fed-ep').value.trim();
    if (!endpoint) { toast('Enter an endpoint URL', false); return; }
    try {
      const r = await fetch('/api/federation/join', {method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({endpoint})});
      const d = await r.json();
      if (d.ok) {
        toast('Joined ' + endpoint, true); $('fed-ep').value = '';
        fetch('/api/federation').then(r=>r.json()).then(d=>updateFederation({data:d})).catch(()=>{});
      } else toast(d.error||'Join failed', false);
    } catch(e) { toast('Network error', false); }
  }

  // ---- Clear memory ----
  async function clearMemory() {
    if (!confirm('Permanently delete ALL episodic, semantic, and procedural memory?\\nThis cannot be undone.')) return;
    try {
      const r = await fetch('/api/memory/clear', {method:'POST'});
      const d = await r.json();
      if (d.ok) {
        toast(`Cleared: ${d.episodic_deleted} episodes, ${d.semantic_deleted} entities, ${d.procedural_deleted} procedures`, true);
        fetch('/api/memory').then(r=>r.json()).then(d=>updateMemory({data:d})).catch(()=>{});
      } else toast(d.error||'Clear failed', false);
    } catch(e) { toast('Network error', false); }
  }

  // ---- Message peer ----
  let peerTarget = '';
  function openMsgPeer(name) {
    peerTarget = name;
    const area = $('peer-msg-area');
    if (area) { area.style.display = 'block'; $('peer-target').textContent = name; $('peer-msg-in').focus(); }
  }
  async function sendPeerMsg() {
    const content = $('peer-msg-in').value.trim();
    if (!content || !peerTarget) return;
    const btn = $('peer-msg-btn'), resp = $('peer-msg-resp');
    btn.disabled = true; btn.textContent = 'Sending...'; resp.style.display = 'none';
    try {
      const r = await fetch('/api/federation/message', {method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({node_name: peerTarget, content})});
      const d = await r.json();
      if (d.ok) { resp.textContent = d.response; resp.style.display = 'block'; $('peer-msg-in').value = ''; }
      else toast(d.error||'Message failed', false);
    } catch(e) { toast('Network error', false); }
    finally { btn.disabled = false; btn.textContent = 'Send'; }
  }

  // ---- Keyboard shortcuts ----
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSpawnModal();
  });

  // ---- Bootstrap ----
  connect();
  fetch('/api/stats').then(r=>r.json()).then(d=>updateStats({data:d})).catch(()=>{});
  fetch('/api/agents').then(r=>r.json()).then(d=>updateAgents({data:d})).catch(()=>{});
  fetch('/api/federation').then(r=>r.json()).then(d=>updateFederation({data:d})).catch(()=>{});
  fetch('/api/memory').then(r=>r.json()).then(d=>updateMemory({data:d})).catch(()=>{});
  fetch('/api/bus').then(r=>r.json()).then(d=>updateBus({data:d})).catch(()=>{});
  loadFeatures();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Dashboard Server
# ---------------------------------------------------------------------------

class Dashboard:
    """
    Lightweight aiohttp-based dashboard for NeuralClaw.

    Routes:
      GET  /                — Dashboard UI
      GET  /api/stats       — System statistics (JSON)
      GET  /api/traces      — Recent reasoning traces (JSON)
      GET  /api/agents      — Active swarm agents (JSON)
      GET  /api/federation  — Federation node status (JSON)
      GET  /api/memory      — Memory health stats (JSON)
      GET  /api/bus         — Recent event bus entries (JSON)
      GET  /api/features    — Feature toggle states (JSON)
      POST /api/spawn       — Spawn a remote agent
      POST /api/despawn     — Despawn a named agent
      POST /api/message     — Send a test message
      POST /api/federation/join — Join a federation peer
      POST /api/memory/clear — Clear all memory stores
      POST /api/features    — Toggle a feature flag
      WS   /ws/traces       — Live trace + data streaming
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        auth_token: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._auth_token = str(auth_token or "").strip()
        self._app: Any = None
        self._runner: Any = None
        self._ws_clients: list[Any] = []
        self._traces: list[dict[str, Any]] = []
        self._start_time = time.time()
        self._push_task: asyncio.Task[None] | None = None

        # Data providers
        self._stats_provider: Any = None
        self._agents_provider: Any = None
        self._federation_provider: Any = None
        self._memory_provider: Any = None
        self._memory_items_provider: Any = None
        self._bus_provider: Any = None
        self._health_provider: Any = None
        self._ready_provider: Any = None
        self._metrics_provider: Any = None
        self._metrics_json_provider: Any = None
        self._trace_list_provider: Any = None
        self._trace_detail_provider: Any = None
        self._config_provider: Any = None
        self._skills_provider: Any = None
        self._swarm_provider: Any = None
        self._tasks_provider: Any = None
        self._task_detail_provider: Any = None
        self._task_approve_action: Any = None
        self._task_reject_action: Any = None
        self._operator_brief_provider: Any = None
        self._audit_provider: Any = None
        self._local_models_provider: Any = None
        self._integrations_provider: Any = None
        self._integration_test_action: Any = None
        self._integration_connect_action: Any = None
        self._integration_disconnect_action: Any = None
        self._integration_callback_action: Any = None
        self._assistant_screen_action: Any = None

        # Action callables
        self._spawn_action: Any = None
        self._despawn_action: Any = None
        self._send_message_action: Any = None
        self._join_federation_action: Any = None
        self._clear_memory_action: Any = None
        self._memory_update_item_action: Any = None
        self._memory_delete_item_action: Any = None
        self._memory_pin_item_action: Any = None
        self._get_features_action: Any = None
        self._set_feature_action: Any = None
        self._message_peer_action: Any = None
        self._provider_reset_action: Any = None
        self._update_config_action: Any = None
        self._channels_provider: Any = None
        self._channel_update_action: Any = None
        self._channel_test_action: Any = None
        self._channel_pair_action: Any = None
        self._channel_reset_action: Any = None
        self._kb_list_action: Any = None
        self._kb_ingest_action: Any = None
        self._kb_ingest_text_action: Any = None
        self._kb_search_action: Any = None
        self._kb_delete_action: Any = None

        # Agent definition CRUD
        self._agent_def_list: Any = None
        self._agent_def_create: Any = None
        self._agent_def_update: Any = None
        self._agent_def_delete: Any = None
        self._agent_def_spawn: Any = None
        self._agent_def_despawn: Any = None
        self._agent_running: Any = None
        self._agent_delegate: Any = None
        self._shared_task_create: Any = None
        self._shared_task_get: Any = None
        self._agent_memories: Any = None
        self._agent_activity: Any = None
        self._agent_auto_route: Any = None
        self._agent_consensus: Any = None
        self._agent_pipeline: Any = None
        self._workflow_list_action: Any = None
        self._workflow_create_action: Any = None
        self._workflow_run_action: Any = None
        self._workflow_pause_action: Any = None
        self._workflow_delete_action: Any = None
        self._memory_export_action: Any = None
        self._memory_import_action: Any = None
        self._memory_retention_action: Any = None

        # Adaptive control plane actions
        self._snapshot_create_action: Any = None
        self._rollback_execute_action: Any = None
        self._snapshot_list_action: Any = None
        self._rollback_status_action: Any = None
        self._routine_create_action: Any = None
        self._routine_list_action: Any = None
        self._routine_update_action: Any = None
        self._routine_outcome_action: Any = None
        self._learning_review_action: Any = None
        self._pending_reviews_action: Any = None
        self._project_activate_action: Any = None
        self._project_suspend_action: Any = None
        self._project_active_action: Any = None
        self._project_sessions_action: Any = None
        self._teaching_capture_action: Any = None
        self._teaching_promote_template_action: Any = None
        self._teaching_promote_skill_action: Any = None
        self._teaching_list_action: Any = None
        self._skill_graph_action: Any = None
        self._skill_resolve_action: Any = None
        self._skill_composition_action: Any = None
        self._sharing_distill_action: Any = None
        self._sharing_export_action: Any = None
        self._sharing_import_action: Any = None
        self._sharing_review_action: Any = None
        self._sharing_list_action: Any = None
        self._multimodal_voice_action: Any = None
        self._multimodal_screenshot_action: Any = None
        self._multimodal_recording_action: Any = None
        self._multimodal_diagram_action: Any = None
        self._multimodal_list_action: Any = None

        # Adaptive wave-2 actions
        self._intent_predictions_action: Any = None
        self._intent_stats_action: Any = None
        self._intent_observe_action: Any = None
        self._style_profile_action: Any = None
        self._style_rule_action: Any = None
        self._compensating_history_action: Any = None
        self._compensating_list_action: Any = None
        self._compensating_plan_action: Any = None
        self._compensating_execute_action: Any = None
        self._federation_skills_action: Any = None
        self._federation_stats_action: Any = None
        self._federation_publish_action: Any = None
        self._federation_import_action: Any = None
        self._scheduler_status_action: Any = None
        self._scheduler_force_action: Any = None

    @staticmethod
    def _is_loopback_host(value: str | None) -> bool:
        host = str(value or "").strip().lower()
        if not host:
            return False
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        return host in {"127.0.0.1", "::1", "localhost"}

    def _request_is_local(self, request: Any) -> bool:
        remote = str(getattr(request, "remote", "") or "").strip()
        if remote and self._is_loopback_host(remote):
            return True
        transport = getattr(request, "transport", None)
        if transport is None:
            return False
        peername = transport.get_extra_info("peername")
        host = peername[0] if isinstance(peername, tuple) and peername else ""
        return self._is_loopback_host(str(host))

    def _request_is_authorized(self, request: Any) -> bool:
        if self._request_is_local(request):
            return True
        if not self._auth_token:
            return False
        header = str(request.headers.get("Authorization", "") or "").strip()
        token = ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        if not token:
            token = str(request.headers.get("X-NeuralClaw-Token", "") or "").strip()
        return bool(token) and secrets.compare_digest(token, self._auth_token)

    def _apply_cors_headers(self, request: Any, response: Any) -> None:
        origin = str(request.headers.get("Origin", "") or "").strip()
        origin_host = urlparse(origin).hostname if origin else ""
        if origin and (self._request_is_local(request) or self._is_loopback_host(origin_host)):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-NeuralClaw-Token"
        )
        response.headers["Access-Control-Max-Age"] = "86400"

    # -- Data provider setters --

    def set_stats_provider(self, provider: Any) -> None:
        self._stats_provider = provider

    def set_agents_provider(self, provider: Any) -> None:
        self._agents_provider = provider

    def set_federation_provider(self, provider: Any) -> None:
        self._federation_provider = provider

    def set_memory_provider(self, provider: Any) -> None:
        self._memory_provider = provider

    def set_memory_management_actions(
        self,
        list_action: Any = None,
        update_item_action: Any = None,
        delete_item_action: Any = None,
        pin_item_action: Any = None,
    ) -> None:
        self._memory_items_provider = list_action
        self._memory_update_item_action = update_item_action
        self._memory_delete_item_action = delete_item_action
        self._memory_pin_item_action = pin_item_action

    def set_bus_provider(self, provider: Any) -> None:
        self._bus_provider = provider

    def set_health_provider(self, provider: Any) -> None:
        self._health_provider = provider

    def set_ready_provider(self, provider: Any) -> None:
        self._ready_provider = provider

    def set_metrics_provider(self, provider: Any) -> None:
        self._metrics_provider = provider

    def set_metrics_json_provider(self, provider: Any) -> None:
        self._metrics_json_provider = provider

    def set_trace_providers(self, list_provider: Any, detail_provider: Any) -> None:
        self._trace_list_provider = list_provider
        self._trace_detail_provider = detail_provider

    def set_config_provider(self, provider: Any) -> None:
        self._config_provider = provider

    def set_config_update_action(self, action: Any) -> None:
        self._update_config_action = action

    def set_channels_provider(self, provider: Any) -> None:
        self._channels_provider = provider

    def set_channel_actions(
        self,
        update_action: Any = None,
        test_action: Any = None,
        pair_action: Any = None,
        reset_action: Any = None,
    ) -> None:
        self._channel_update_action = update_action
        self._channel_test_action = test_action
        self._channel_pair_action = pair_action
        self._channel_reset_action = reset_action

    def set_skills_provider(self, provider: Any) -> None:
        self._skills_provider = provider

    def set_swarm_provider(self, provider: Any) -> None:
        self._swarm_provider = provider

    def set_task_providers(
        self,
        list_provider: Any = None,
        detail_provider: Any = None,
        approve_action: Any = None,
        reject_action: Any = None,
    ) -> None:
        self._tasks_provider = list_provider
        self._task_detail_provider = detail_provider
        self._task_approve_action = approve_action
        self._task_reject_action = reject_action

    def set_local_models_provider(self, provider: Any) -> None:
        self._local_models_provider = provider

    def set_operator_brief_provider(self, provider: Any) -> None:
        self._operator_brief_provider = provider

    def set_audit_provider(self, provider: Any) -> None:
        self._audit_provider = provider

    def set_integrations_provider(self, provider: Any) -> None:
        self._integrations_provider = provider

    def set_integration_actions(
        self,
        test_action: Any = None,
        connect_action: Any = None,
        disconnect_action: Any = None,
        callback_action: Any = None,
    ) -> None:
        self._integration_test_action = test_action
        self._integration_connect_action = connect_action
        self._integration_disconnect_action = disconnect_action
        self._integration_callback_action = callback_action

    def set_knowledge_base_actions(
        self,
        list_action: Any = None,
        ingest_action: Any = None,
        ingest_text_action: Any = None,
        search_action: Any = None,
        delete_action: Any = None,
    ) -> None:
        self._kb_list_action = list_action
        self._kb_ingest_action = ingest_action
        self._kb_ingest_text_action = ingest_text_action
        self._kb_search_action = search_action
        self._kb_delete_action = delete_action

    def set_assistant_actions(self, screen_action: Any = None) -> None:
        self._assistant_screen_action = screen_action

    # -- Action setters --

    def set_spawn_action(self, action: Any) -> None:
        self._spawn_action = action

    def set_despawn_action(self, action: Any) -> None:
        self._despawn_action = action

    def set_send_message_action(self, action: Any) -> None:
        self._send_message_action = action

    def set_join_federation_action(self, action: Any) -> None:
        self._join_federation_action = action

    def set_clear_memory_action(self, action: Any) -> None:
        self._clear_memory_action = action

    def set_memory_backup_actions(
        self,
        export_action: Any = None,
        import_action: Any = None,
        retention_action: Any = None,
    ) -> None:
        self._memory_export_action = export_action
        self._memory_import_action = import_action
        self._memory_retention_action = retention_action

    def set_features_provider(self, getter: Any, setter: Any) -> None:
        self._get_features_action = getter
        self._set_feature_action = setter

    def set_message_peer_action(self, action: Any) -> None:
        self._message_peer_action = action

    def set_provider_reset_action(self, action: Any) -> None:
        self._provider_reset_action = action

    def set_agent_definition_actions(
        self,
        list_fn: Any = None,
        create_fn: Any = None,
        update_fn: Any = None,
        delete_fn: Any = None,
        spawn_fn: Any = None,
        despawn_fn: Any = None,
        running_fn: Any = None,
        delegate_fn: Any = None,
        shared_task_create_fn: Any = None,
        shared_task_get_fn: Any = None,
        memories_fn: Any = None,
        activity_fn: Any = None,
        auto_route_fn: Any = None,
        consensus_fn: Any = None,
        pipeline_fn: Any = None,
    ) -> None:
        self._agent_def_list = list_fn
        self._agent_def_create = create_fn
        self._agent_def_update = update_fn
        self._agent_def_delete = delete_fn
        self._agent_def_spawn = spawn_fn
        self._agent_def_despawn = despawn_fn
        self._agent_running = running_fn
        self._agent_delegate = delegate_fn
        self._shared_task_create = shared_task_create_fn
        self._shared_task_get = shared_task_get_fn
        self._agent_memories = memories_fn
        self._agent_activity = activity_fn
        self._agent_auto_route = auto_route_fn
        self._agent_consensus = consensus_fn
        self._agent_pipeline = pipeline_fn

    def set_workflow_actions(
        self,
        list_action: Any = None,
        create_action: Any = None,
        run_action: Any = None,
        pause_action: Any = None,
        delete_action: Any = None,
    ) -> None:
        self._workflow_list_action = list_action
        self._workflow_create_action = create_action
        self._workflow_run_action = run_action
        self._workflow_pause_action = pause_action
        self._workflow_delete_action = delete_action

    def set_adaptive_actions(
        self,
        snapshot_create: Any = None,
        rollback_execute: Any = None,
        snapshot_list: Any = None,
        rollback_status: Any = None,
        routine_create: Any = None,
        routine_list: Any = None,
        routine_update: Any = None,
        routine_outcome: Any = None,
        learning_review: Any = None,
        pending_reviews: Any = None,
        project_activate: Any = None,
        project_suspend: Any = None,
        project_active: Any = None,
        project_sessions: Any = None,
        teaching_capture: Any = None,
        teaching_promote_template: Any = None,
        teaching_promote_skill: Any = None,
        teaching_list: Any = None,
        skill_graph: Any = None,
        skill_resolve: Any = None,
        skill_composition: Any = None,
        sharing_distill: Any = None,
        sharing_export: Any = None,
        sharing_import: Any = None,
        sharing_review: Any = None,
        sharing_list: Any = None,
        multimodal_voice: Any = None,
        multimodal_screenshot: Any = None,
        multimodal_recording: Any = None,
        multimodal_diagram: Any = None,
        multimodal_list: Any = None,
        intent_predictions: Any = None,
        intent_stats: Any = None,
        intent_observe: Any = None,
        style_profile: Any = None,
        style_rule: Any = None,
        compensating_history: Any = None,
        compensating_list: Any = None,
        compensating_plan: Any = None,
        compensating_execute: Any = None,
        federation_skills: Any = None,
        federation_stats: Any = None,
        federation_publish: Any = None,
        federation_import: Any = None,
        scheduler_status: Any = None,
        scheduler_force: Any = None,
    ) -> None:
        self._snapshot_create_action = snapshot_create
        self._rollback_execute_action = rollback_execute
        self._snapshot_list_action = snapshot_list
        self._rollback_status_action = rollback_status
        self._routine_create_action = routine_create
        self._routine_list_action = routine_list
        self._routine_update_action = routine_update
        self._routine_outcome_action = routine_outcome
        self._learning_review_action = learning_review
        self._pending_reviews_action = pending_reviews
        self._project_activate_action = project_activate
        self._project_suspend_action = project_suspend
        self._project_active_action = project_active
        self._project_sessions_action = project_sessions
        self._teaching_capture_action = teaching_capture
        self._teaching_promote_template_action = teaching_promote_template
        self._teaching_promote_skill_action = teaching_promote_skill
        self._teaching_list_action = teaching_list
        self._skill_graph_action = skill_graph
        self._skill_resolve_action = skill_resolve
        self._skill_composition_action = skill_composition
        self._sharing_distill_action = sharing_distill
        self._sharing_export_action = sharing_export
        self._sharing_import_action = sharing_import
        self._sharing_review_action = sharing_review
        self._sharing_list_action = sharing_list
        self._multimodal_voice_action = multimodal_voice
        self._multimodal_screenshot_action = multimodal_screenshot
        self._multimodal_recording_action = multimodal_recording
        self._multimodal_diagram_action = multimodal_diagram
        self._multimodal_list_action = multimodal_list
        self._intent_predictions_action = intent_predictions
        self._intent_stats_action = intent_stats
        self._intent_observe_action = intent_observe
        self._style_profile_action = style_profile
        self._style_rule_action = style_rule
        self._compensating_history_action = compensating_history
        self._compensating_list_action = compensating_list
        self._compensating_plan_action = compensating_plan
        self._compensating_execute_action = compensating_execute
        self._federation_skills_action = federation_skills
        self._federation_stats_action = federation_stats
        self._federation_publish_action = federation_publish
        self._federation_import_action = federation_import
        self._scheduler_status_action = scheduler_status
        self._scheduler_force_action = scheduler_force

    # -- Trace push --

    def push_trace(self, category: str, message: str, data: dict[str, Any] | None = None) -> None:
        trace = {
            "type": "trace",
            "category": category,
            "message": message,
            "timestamp": time.time(),
            "data": data or {},
        }
        self._traces.append(trace)
        if len(self._traces) > 500:
            self._traces = self._traces[-500:]
        asyncio.ensure_future(self._broadcast(trace))

    # -- Lifecycle --

    async def start(self) -> None:
        if web is None:
            print("[Dashboard] aiohttp not installed — dashboard unavailable")
            return

        self._app = web.Application(middlewares=[_dashboard_security_middleware])
        self._app["dashboard_instance"] = self
        # GET routes
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/stats", self._handle_stats)
        self._app.router.add_get("/api/traces", self._handle_traces)
        self._app.router.add_get("/api/agents", self._handle_agents)
        self._app.router.add_get("/api/federation", self._handle_federation)
        self._app.router.add_get("/api/memory", self._handle_memory)
        self._app.router.add_get("/api/memory/items", self._handle_memory_items)
        self._app.router.add_get("/api/bus", self._handle_bus)
        self._app.router.add_get("/api/features", self._handle_get_features)
        self._app.router.add_get("/traces", self._handle_trace_list)
        self._app.router.add_get("/traces/{trace_id}", self._handle_trace_detail)
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/ready", self._handle_ready)
        self._app.router.add_get("/metrics", self._handle_metrics)
        self._app.router.add_get("/config", self._handle_config)
        self._app.router.add_get("/api/channels", self._handle_channels)
        self._app.router.add_get("/api/tasks", self._handle_tasks)
        self._app.router.add_get("/api/tasks/{task_id}", self._handle_task_detail)
        self._app.router.add_get("/api/operator/brief", self._handle_operator_brief)
        self._app.router.add_get("/api/audit", self._handle_audit)
        self._app.router.add_get("/api/adaptive/routines", self._handle_adaptive_routines)
        self._app.router.add_get("/api/adaptive/reviews", self._handle_adaptive_reviews)
        self._app.router.add_get("/api/adaptive/projects", self._handle_adaptive_projects)
        self._app.router.add_get("/api/adaptive/project/active", self._handle_adaptive_active_project)
        self._app.router.add_get("/api/adaptive/snapshots", self._handle_adaptive_snapshots)
        self._app.router.add_get("/api/adaptive/skills/graph", self._handle_adaptive_skill_graph)
        self._app.router.add_get("/api/adaptive/teaching", self._handle_adaptive_teaching)
        self._app.router.add_post("/api/tasks/{task_id}/approve", self._handle_task_approve)
        self._app.router.add_post("/api/tasks/{task_id}/reject", self._handle_task_reject)
        self._app.router.add_get("/api/models/local-health", self._handle_local_models)
        self._app.router.add_get("/api/integrations", self._handle_integrations)
        self._app.router.add_post("/api/integrations/{integration_id}/connect", self._handle_integration_connect)
        self._app.router.add_post("/api/integrations/{integration_id}/test", self._handle_integration_test)
        self._app.router.add_post("/api/integrations/{integration_id}/disconnect", self._handle_integration_disconnect)
        self._app.router.add_get("/api/integrations/oauth/{provider}/callback", self._handle_integration_callback)
        self._app.router.add_get("/skills", self._handle_skills)
        self._app.router.add_get("/swarm", self._handle_swarm)
        self._app.router.add_get("/ws/traces", self._handle_ws)
        self._app.router.add_get("/ws", self._handle_ws)
        # POST routes
        self._app.router.add_post("/api/spawn", self._handle_spawn)
        self._app.router.add_post("/api/despawn", self._handle_despawn)
        self._app.router.add_post("/api/message", self._handle_message)
        self._app.router.add_post("/api/federation/join", self._handle_federation_join)
        self._app.router.add_post("/api/memory/clear", self._handle_memory_clear)
        self._app.router.add_post("/api/memory/export", self._handle_memory_export)
        self._app.router.add_post("/api/memory/import", self._handle_memory_import)
        self._app.router.add_post("/api/memory/retention", self._handle_memory_retention)
        self._app.router.add_post("/api/memory/items/{store}/{item_id}/pin", self._handle_memory_item_pin)
        self._app.router.add_post("/api/features", self._handle_set_feature)
        self._app.router.add_post("/api/config", self._handle_config_update)
        self._app.router.add_post("/api/channels/{channel_name}", self._handle_channel_update)
        self._app.router.add_post("/api/channels/{channel_name}/test", self._handle_channel_test)
        self._app.router.add_post("/api/channels/{channel_name}/pair", self._handle_channel_pair)
        self._app.router.add_post("/api/channels/{channel_name}/reset", self._handle_channel_reset)
        self._app.router.add_post("/api/assistant/screen", self._handle_assistant_screen)
        self._app.router.add_get("/api/kb/documents", self._handle_kb_documents)
        self._app.router.add_post("/api/kb/ingest", self._handle_kb_ingest)
        self._app.router.add_post("/api/kb/ingest-text", self._handle_kb_ingest_text)
        self._app.router.add_post("/api/kb/search", self._handle_kb_search)
        self._app.router.add_delete("/api/kb/documents/{document_id}", self._handle_kb_delete)
        self._app.router.add_put("/api/memory/items/{store}/{item_id}", self._handle_memory_item_update)
        self._app.router.add_delete("/api/memory/items/{store}/{item_id}", self._handle_memory_item_delete)
        self._app.router.add_post("/api/federation/message", self._handle_message_peer)
        self._app.router.add_post("/api/provider/reset-circuit", self._handle_provider_reset)
        self._app.router.add_post("/api/adaptive/reviews/{cycle_id}", self._handle_adaptive_review_action)
        self._app.router.add_post("/api/adaptive/routines/{routine_id}", self._handle_adaptive_routine_action)
        self._app.router.add_post("/api/adaptive/projects/activate", self._handle_adaptive_project_activate)
        self._app.router.add_post("/api/adaptive/projects/suspend", self._handle_adaptive_project_suspend)
        self._app.router.add_post("/api/adaptive/snapshots", self._handle_adaptive_snapshot_create)
        self._app.router.add_post("/api/adaptive/rollback", self._handle_adaptive_rollback)
        self._app.router.add_post("/api/adaptive/teaching/capture", self._handle_adaptive_teaching_capture)
        self._app.router.add_post("/api/adaptive/sharing/export", self._handle_adaptive_sharing_export)
        self._app.router.add_post("/api/adaptive/sharing/import", self._handle_adaptive_sharing_import)
        self._app.router.add_post("/api/adaptive/multimodal/{kind}", self._handle_adaptive_multimodal)
        # Adaptive wave-2 routes
        self._app.router.add_get("/api/adaptive/intent/predictions", self._handle_adaptive_intent_predictions)
        self._app.router.add_get("/api/adaptive/intent/stats", self._handle_adaptive_intent_stats)
        self._app.router.add_get("/api/adaptive/style/profile", self._handle_adaptive_style_profile)
        self._app.router.add_get("/api/adaptive/compensating/history", self._handle_adaptive_compensating_history)
        self._app.router.add_get("/api/adaptive/compensating/compensators", self._handle_adaptive_compensating_list)
        self._app.router.add_get("/api/adaptive/federation/skills", self._handle_adaptive_federation_skills)
        self._app.router.add_get("/api/adaptive/federation/stats", self._handle_adaptive_federation_stats)
        self._app.router.add_get("/api/adaptive/scheduler/status", self._handle_adaptive_scheduler_status)
        self._app.router.add_post("/api/adaptive/intent/observe", self._handle_adaptive_intent_observe)
        self._app.router.add_post("/api/adaptive/style/rule", self._handle_adaptive_style_rule)
        self._app.router.add_post("/api/adaptive/compensating/plan", self._handle_adaptive_compensating_plan)
        self._app.router.add_post("/api/adaptive/compensating/execute", self._handle_adaptive_compensating_execute)
        self._app.router.add_post("/api/adaptive/federation/publish", self._handle_adaptive_federation_publish)
        self._app.router.add_post("/api/adaptive/federation/import", self._handle_adaptive_federation_import)
        self._app.router.add_post("/api/adaptive/scheduler/force", self._handle_adaptive_scheduler_force)
        # Agent definition CRUD routes
        self._app.router.add_get("/api/agents/definitions", self._handle_agent_def_list)
        self._app.router.add_post("/api/agents/definitions", self._handle_agent_def_create)
        self._app.router.add_put("/api/agents/definitions/{agent_id}", self._handle_agent_def_update)
        self._app.router.add_delete("/api/agents/definitions/{agent_id}", self._handle_agent_def_delete)
        self._app.router.add_post("/api/agents/definitions/{agent_id}/spawn", self._handle_agent_def_spawn)
        self._app.router.add_post("/api/agents/definitions/{agent_id}/despawn", self._handle_agent_def_despawn)
        self._app.router.add_get("/api/agents/running", self._handle_agents_running)
        self._app.router.add_get("/api/agents/activity", self._handle_agent_activity)
        self._app.router.add_get("/api/agents/{agent_name}/memories", self._handle_agent_memories)
        self._app.router.add_post("/api/agents/delegate", self._handle_agent_delegate)
        self._app.router.add_post("/api/agents/shared-task", self._handle_shared_task_create)
        self._app.router.add_get("/api/agents/shared-task/{task_id}", self._handle_shared_task_get)
        self._app.router.add_post("/api/agents/auto-route", self._handle_agent_auto_route)
        self._app.router.add_post("/api/agents/consensus", self._handle_agent_consensus)
        self._app.router.add_post("/api/agents/pipeline", self._handle_agent_pipeline)
        # Workflow routes
        self._app.router.add_get("/api/workflows", self._handle_workflow_list)
        self._app.router.add_post("/api/workflows", self._handle_workflow_create)
        self._app.router.add_post("/api/workflows/{workflow_id}/run", self._handle_workflow_run)
        self._app.router.add_post("/api/workflows/{workflow_id}/pause", self._handle_workflow_pause)
        self._app.router.add_delete("/api/workflows/{workflow_id}", self._handle_workflow_delete)
        # Database BI routes
        self._app.router.add_get("/api/db/connections", self._handle_db_connections)
        self._app.router.add_post("/api/db/connect", self._handle_db_connect)
        self._app.router.add_post("/api/db/disconnect", self._handle_db_disconnect)
        self._app.router.add_get("/api/db/tables", self._handle_db_tables)
        self._app.router.add_post("/api/db/query", self._handle_db_query)
        self._app.router.add_post("/api/db/natural-query", self._handle_db_natural_query)
        self._app.router.add_post("/api/db/chart", self._handle_db_chart)
        self._app.router.add_post("/api/db/explain", self._handle_db_explain)
        self._app.router.add_get("/api/db/describe/{connection}/{table}", self._handle_db_describe)
        # Provider models route
        self._app.router.add_get("/api/providers/{provider_name}/models", self._handle_provider_models)
        self._app.router.add_get("/api/providers/status", self._handle_provider_status)
        # Workspace + Skills routes
        self._app.router.add_get("/api/workspace/structure", self._handle_workspace_structure)
        self._app.router.add_get("/api/workspace/projects", self._handle_workspace_projects)
        self._app.router.add_post("/api/workspace/projects", self._handle_workspace_scaffold)
        self._app.router.add_get("/api/workspace/projects/{name}", self._handle_workspace_project_detail)
        self._app.router.add_post("/api/workspace/projects/{name}/component", self._handle_workspace_project_add)
        self._app.router.add_get("/api/workspace/claims", self._handle_workspace_claims)
        self._app.router.add_post("/api/workspace/claim", self._handle_workspace_claim)
        self._app.router.add_delete("/api/workspace/claim", self._handle_workspace_release)
        self._app.router.add_get("/api/skills/available", self._handle_skills_available)
        self._app.router.add_get("/api/skills/template", self._handle_skills_template)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        self._push_task = asyncio.create_task(self._periodic_push())
        print(f"[Dashboard] Running at http://{self._host}:{self._port}")

    async def stop(self) -> None:
        if self._push_task:
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass
        for ws_client in self._ws_clients:
            await ws_client.close()
        if self._runner:
            await self._runner.cleanup()

    # -- GET handlers --

    async def _handle_index(self, request: Any) -> Any:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def _handle_stats(self, request: Any) -> Any:
        stats = self._stats_provider() if self._stats_provider else {}
        if asyncio.iscoroutine(stats):
            stats = await stats
        stats["uptime"] = self._format_uptime()
        return web.json_response(stats)

    async def _handle_traces(self, request: Any) -> Any:
        limit = int(request.query.get("limit", "50"))
        data = self._trace_list_provider(limit) if self._trace_list_provider else self._traces[-limit:]
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_agents(self, request: Any) -> Any:
        agents = self._agents_provider() if self._agents_provider else []
        return web.json_response(agents)

    async def _handle_federation(self, request: Any) -> Any:
        data = self._federation_provider() if self._federation_provider else {"total_nodes": 0, "online_nodes": 0, "nodes": []}
        return web.json_response(data)

    async def _handle_memory(self, request: Any) -> Any:
        data: dict[str, Any] = {"episodic_count": 0, "semantic_count": 0, "procedural_count": 0}
        if self._memory_provider:
            result = self._memory_provider()
            if asyncio.iscoroutine(result):
                result = await result
            data = result
        return web.json_response(data)

    async def _handle_memory_items(self, request: Any) -> Any:
        if not self._memory_items_provider:
            return web.json_response({"items": []})
        store = str(request.query.get("store", "episodic")).strip()
        query = str(request.query.get("query", "")).strip()
        limit = int(request.query.get("limit", "50"))
        result = self._memory_items_provider(store, query, limit)
        if asyncio.iscoroutine(result):
            result = await result
        return web.json_response(result)

    async def _handle_bus(self, request: Any) -> Any:
        data = self._bus_provider() if self._bus_provider else []
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_tasks(self, request: Any) -> Any:
        limit = int(request.query.get("limit", "100"))
        data = self._tasks_provider(limit) if self._tasks_provider else []
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_task_detail(self, request: Any) -> Any:
        task_id = str(request.match_info.get("task_id", "")).strip()
        if not task_id:
            return web.json_response({"error": "task_id required"}, status=400)
        data = self._task_detail_provider(task_id) if self._task_detail_provider else None
        if asyncio.iscoroutine(data):
            data = await data
        if not data:
            return web.json_response({"error": "Task not found"}, status=404)
        return web.json_response(data)

    async def _handle_task_approve(self, request: Any) -> Any:
        if not self._task_approve_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            task_id = str(request.match_info.get("task_id", "")).strip()
            body = await request.json() if request.can_read_body else {}
            payload = body if isinstance(body, dict) else {}
            result = self._task_approve_action(task_id, payload)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_task_reject(self, request: Any) -> Any:
        if not self._task_reject_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            task_id = str(request.match_info.get("task_id", "")).strip()
            body = await request.json() if request.can_read_body else {}
            payload = body if isinstance(body, dict) else {}
            result = self._task_reject_action(task_id, payload)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_local_models(self, request: Any) -> Any:
        data = self._local_models_provider() if self._local_models_provider else {"models": [], "badges": []}
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_operator_brief(self, request: Any) -> Any:
        data = self._operator_brief_provider() if self._operator_brief_provider else {"ok": True, "highlights": [], "recommended_actions": []}
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _invoke_dashboard_action(self, action: Any, *args: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        if not action:
            return default or {"ok": False, "error": "Not available"}
        result = action(*args)
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, dict) else {"ok": True, "result": result}

    async def _handle_adaptive_routines(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._routine_list_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_reviews(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._pending_reviews_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_projects(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._project_sessions_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_active_project(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._project_active_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_snapshots(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._snapshot_list_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_skill_graph(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._skill_graph_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_teaching(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._teaching_list_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_review_action(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._learning_review_action, str(request.match_info.get("cycle_id", "")).strip(), body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_routine_action(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._routine_update_action, str(request.match_info.get("routine_id", "")).strip(), body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_project_activate(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._project_activate_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_project_suspend(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._project_suspend_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_snapshot_create(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._snapshot_create_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_rollback(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._rollback_execute_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_teaching_capture(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._teaching_capture_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_sharing_export(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._sharing_export_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_sharing_import(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._sharing_import_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_multimodal(self, request: Any) -> Any:
        kind = str(request.match_info.get("kind", "")).strip().lower()
        body = await request.json() if request.can_read_body else {}
        action = {
            "voice": self._multimodal_voice_action,
            "screenshot": self._multimodal_screenshot_action,
            "recording": self._multimodal_recording_action,
            "diagram": self._multimodal_diagram_action,
        }.get(kind)
        result = await self._invoke_dashboard_action(action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    # -- Adaptive wave-2 handlers --

    async def _handle_adaptive_intent_predictions(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._intent_predictions_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_intent_stats(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._intent_stats_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_style_profile(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._style_profile_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_compensating_history(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._compensating_history_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_compensating_list(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._compensating_list_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_federation_skills(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._federation_skills_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_federation_stats(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._federation_stats_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_scheduler_status(self, request: Any) -> Any:
        result = await self._invoke_dashboard_action(self._scheduler_status_action, dict(request.query))
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_intent_observe(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._intent_observe_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_style_rule(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._style_rule_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_compensating_plan(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._compensating_plan_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_compensating_execute(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._compensating_execute_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_federation_publish(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._federation_publish_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_federation_import(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._federation_import_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_adaptive_scheduler_force(self, request: Any) -> Any:
        body = await request.json() if request.can_read_body else {}
        result = await self._invoke_dashboard_action(self._scheduler_force_action, body if isinstance(body, dict) else {})
        return web.json_response(result, status=200 if result.get("ok", False) else 400)

    async def _handle_audit(self, request: Any) -> Any:
        query = {
            "limit": request.query.get("limit", "20"),
            "tool": request.query.get("tool", ""),
            "user_id": request.query.get("user_id", ""),
            "denied_only": request.query.get("denied_only", "false"),
        }
        data = self._audit_provider(query) if self._audit_provider else {"ok": True, "events": [], "stats": {}}
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_integrations(self, request: Any) -> Any:
        data = self._integrations_provider() if self._integrations_provider else {"integrations": []}
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_integration_test(self, request: Any) -> Any:
        if not self._integration_test_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            integration_id = str(request.match_info.get("integration_id", "")).strip()
            body = await request.json() if request.can_read_body else {}
            result = self._integration_test_action(integration_id, body if isinstance(body, dict) else {})
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_integration_connect(self, request: Any) -> Any:
        if not self._integration_connect_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            integration_id = str(request.match_info.get("integration_id", "")).strip()
            body = await request.json() if request.can_read_body else {}
            result = self._integration_connect_action(integration_id, body if isinstance(body, dict) else {})
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_integration_disconnect(self, request: Any) -> Any:
        if not self._integration_disconnect_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            integration_id = str(request.match_info.get("integration_id", "")).strip()
            result = self._integration_disconnect_action(integration_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_integration_callback(self, request: Any) -> Any:
        if not self._integration_callback_action:
            return web.Response(text="Not available", status=503)
        try:
            provider = str(request.match_info.get("provider", "")).strip()
            params = dict(request.query)
            result = self._integration_callback_action(provider, params)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            title = "Connection complete" if result.get("ok", False) else "Connection failed"
            message = result.get("message") or result.get("error") or "You can close this window and return to NeuralClaw."
            html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}}
.card{{max-width:560px;width:100%;background:#161b22;border:1px solid #30363d;border-radius:16px;padding:28px;box-shadow:0 18px 50px rgba(0,0,0,.35)}}
h1{{margin:0 0 12px;font-size:24px}} p{{margin:0;color:#9da7b3;line-height:1.6}} .ok{{color:#3fb950}} .err{{color:#f85149}}
</style></head>
<body><div class="card"><h1 class="{'ok' if result.get('ok', False) else 'err'}">{title}</h1><p>{message}</p></div></body></html>"""
            return web.Response(text=html, status=status, content_type="text/html")
        except Exception as e:
            return web.Response(text=f"Callback error: {e}", status=500)

    async def _handle_get_features(self, request: Any) -> Any:
        features = self._get_features_action() if self._get_features_action else {}
        return web.json_response(features)

    async def _handle_trace_list(self, request: Any) -> Any:
        limit = int(request.query.get("limit", "50"))
        data = self._trace_list_provider(limit) if self._trace_list_provider else self._traces[-limit:]
        if asyncio.iscoroutine(data):
            data = await data
        return web.json_response(data)

    async def _handle_trace_detail(self, request: Any) -> Any:
        trace_id = str(request.match_info.get("trace_id", "")).strip()
        if not trace_id:
            return web.json_response({"error": "trace_id required"}, status=400)
        data = self._trace_detail_provider(trace_id) if self._trace_detail_provider else None
        if asyncio.iscoroutine(data):
            data = await data
        if not data:
            return web.json_response({"error": "trace not found"}, status=404)
        return web.json_response(data)

    async def _handle_health(self, request: Any) -> Any:
        payload = self._health_provider() if self._health_provider else {"status": "unhealthy"}
        status = 200 if payload.get("status") == "healthy" else 503
        return web.json_response(payload, status=status)

    async def _handle_ready(self, request: Any) -> Any:
        payload = self._ready_provider() if self._ready_provider else {"status": "starting"}
        status = 200 if payload.get("status") in {"ready", "degraded"} else 503
        return web.json_response(payload, status=status)

    async def _handle_metrics(self, request: Any) -> Any:
        accept = str(request.headers.get("Accept", "")).lower()
        wants_json = request.query.get("format") == "json" or "application/json" in accept
        if wants_json and self._metrics_json_provider:
            payload = self._metrics_json_provider()
            if asyncio.iscoroutine(payload):
                payload = await payload
            return web.json_response(payload)
        payload = ""
        if self._metrics_provider:
            payload = self._metrics_provider()
            if asyncio.iscoroutine(payload):
                payload = await payload
        return web.Response(text=str(payload), content_type="text/plain")

    async def _handle_config(self, request: Any) -> Any:
        payload = self._config_provider() if self._config_provider else {}
        if asyncio.iscoroutine(payload):
            payload = await payload
        return web.json_response(payload)

    async def _handle_channels(self, request: Any) -> Any:
        payload = self._channels_provider() if self._channels_provider else []
        if asyncio.iscoroutine(payload):
            payload = await payload
        return web.json_response(payload)

    async def _handle_assistant_screen(self, request: Any) -> Any:
        if not self._assistant_screen_action:
            return web.json_response({"ok": False, "error": "Assistant screen preview not available"}, status=503)
        try:
            body = await request.json() if request.can_read_body else {}
            if not isinstance(body, dict):
                body = {}
            result = self._assistant_screen_action(body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_skills(self, request: Any) -> Any:
        payload = self._skills_provider() if self._skills_provider else []
        if asyncio.iscoroutine(payload):
            payload = await payload
        return web.json_response(payload)

    async def _handle_swarm(self, request: Any) -> Any:
        payload = self._swarm_provider() if self._swarm_provider else []
        if asyncio.iscoroutine(payload):
            payload = await payload
        return web.json_response(payload)

    # -- POST handlers --

    async def _handle_spawn(self, request: Any) -> Any:
        if not self._spawn_action:
            return web.json_response({"ok": False, "error": "Spawn not available"}, status=503)
        try:
            body = await request.json()
            name = str(body.get("name", "")).strip()
            desc = str(body.get("description", "")).strip()
            caps = [c.strip() for c in str(body.get("capabilities", "")).split(",") if c.strip()]
            endpoint = str(body.get("endpoint", "")).strip()
            if not name or not endpoint:
                return web.json_response({"ok": False, "error": "name and endpoint required"}, status=400)
            result = self._spawn_action(name, desc, caps, endpoint)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_despawn(self, request: Any) -> Any:
        if not self._despawn_action:
            return web.json_response({"ok": False, "error": "Despawn not available"}, status=503)
        try:
            body = await request.json()
            name = str(body.get("name", "")).strip()
            if not name:
                return web.json_response({"ok": False, "error": "name required"}, status=400)
            ok = self._despawn_action(name)
            return web.json_response({"ok": bool(ok)})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_message(self, request: Any) -> Any:
        if not self._send_message_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            content = str(body.get("content", "")).strip()
            if not content:
                return web.json_response({"ok": False, "error": "content required"}, status=400)
            payload = dict(body)
            payload["content"] = content
            response = self._send_message_action(payload)
            if asyncio.iscoroutine(response):
                response = await response
            if isinstance(response, dict) and "ok" in response:
                status = 200 if response.get("ok", False) else 400
                return web.json_response(response, status=status)
            return web.json_response({"ok": True, "response": response})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_federation_join(self, request: Any) -> Any:
        if not self._join_federation_action:
            return web.json_response({"ok": False, "error": "Federation not available"}, status=503)
        try:
            body = await request.json()
            endpoint = str(body.get("endpoint", "")).strip()
            if not endpoint:
                return web.json_response({"ok": False, "error": "endpoint required"}, status=400)
            ok = self._join_federation_action(endpoint)
            if asyncio.iscoroutine(ok):
                ok = await ok
            return web.json_response({"ok": bool(ok)})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_clear(self, request: Any) -> Any:
        if not self._clear_memory_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            try:
                body = await request.json() if request.can_read_body else {}
            except Exception:
                body = {}
            result = self._clear_memory_action(body or {})
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response({"ok": True, **result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_export(self, request: Any) -> Any:
        if not self._memory_export_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json() if request.can_read_body else {}
            result = self._memory_export_action(body or {})
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_import(self, request: Any) -> Any:
        if not self._memory_import_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            result = self._memory_import_action(body or {})
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_retention(self, request: Any) -> Any:
        if not self._memory_retention_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json() if request.can_read_body else {}
            result = self._memory_retention_action(body or {})
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_item_update(self, request: Any) -> Any:
        if not self._memory_update_item_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            store = str(request.match_info.get("store", "")).strip()
            item_id = str(request.match_info.get("item_id", "")).strip()
            body = await request.json()
            result = self._memory_update_item_action(store, item_id, body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_item_delete(self, request: Any) -> Any:
        if not self._memory_delete_item_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            store = str(request.match_info.get("store", "")).strip()
            item_id = str(request.match_info.get("item_id", "")).strip()
            result = self._memory_delete_item_action(store, item_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_memory_item_pin(self, request: Any) -> Any:
        if not self._memory_pin_item_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            store = str(request.match_info.get("store", "")).strip()
            item_id = str(request.match_info.get("item_id", "")).strip()
            result = self._memory_pin_item_action(store, item_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_set_feature(self, request: Any) -> Any:
        if not self._set_feature_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            feature = str(body.get("feature", "")).strip()
            value = bool(body.get("value", False))
            if not feature:
                return web.json_response({"ok": False, "error": "feature required"}, status=400)
            result = self._set_feature_action(feature, value)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, dict):
                status = 200 if result.get("ok", False) else 400
                return web.json_response(result, status=status)
            return web.json_response({"ok": bool(result)})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_config_update(self, request: Any) -> Any:
        if not self._update_config_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            result = self._update_config_action(body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_channel_update(self, request: Any) -> Any:
        if not self._channel_update_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            channel_name = str(request.match_info.get("channel_name", "")).strip()
            body = await request.json()
            result = self._channel_update_action(channel_name, body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_channel_test(self, request: Any) -> Any:
        if not self._channel_test_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            channel_name = str(request.match_info.get("channel_name", "")).strip()
            body = await request.json()
            result = self._channel_test_action(channel_name, body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_channel_pair(self, request: Any) -> Any:
        if not self._channel_pair_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            channel_name = str(request.match_info.get("channel_name", "")).strip()
            body = await request.json()
            result = self._channel_pair_action(channel_name, body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_channel_reset(self, request: Any) -> Any:
        if not self._channel_reset_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            channel_name = str(request.match_info.get("channel_name", "")).strip()
            result = self._channel_reset_action(channel_name)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_kb_documents(self, request: Any) -> Any:
        if not self._kb_list_action:
            return web.json_response({"ok": False, "error": "Knowledge base not available"}, status=503)
        try:
            result = self._kb_list_action()
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_kb_ingest(self, request: Any) -> Any:
        if not self._kb_ingest_action:
            return web.json_response({"ok": False, "error": "Knowledge base not available"}, status=503)
        try:
            body = await request.json()
            result = self._kb_ingest_action(body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_kb_ingest_text(self, request: Any) -> Any:
        if not self._kb_ingest_text_action:
            return web.json_response({"ok": False, "error": "Knowledge base not available"}, status=503)
        try:
            body = await request.json()
            result = self._kb_ingest_text_action(body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_kb_search(self, request: Any) -> Any:
        if not self._kb_search_action:
            return web.json_response({"ok": False, "error": "Knowledge base not available"}, status=503)
        try:
            body = await request.json()
            result = self._kb_search_action(str(body.get("query", "")).strip())
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_kb_delete(self, request: Any) -> Any:
        if not self._kb_delete_action:
            return web.json_response({"ok": False, "error": "Knowledge base not available"}, status=503)
        try:
            document_id = str(request.match_info.get("document_id", "")).strip()
            if not document_id:
                return web.json_response({"ok": False, "error": "document_id required"}, status=400)
            result = self._kb_delete_action(document_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_message_peer(self, request: Any) -> Any:
        if not self._message_peer_action:
            return web.json_response({"ok": False, "error": "Federation not available"}, status=503)
        try:
            body = await request.json()
            node_name = str(body.get("node_name", "")).strip()
            content = str(body.get("content", "")).strip()
            if not node_name or not content:
                return web.json_response({"ok": False, "error": "node_name and content required"}, status=400)
            result = self._message_peer_action(node_name, content)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_provider_reset(self, request: Any) -> Any:
        if not self._provider_reset_action:
            return web.json_response({"ok": False, "error": "Provider control not available"}, status=503)
        try:
            body = await request.json()
            name = str(body.get("name", "")).strip()
            if not name:
                return web.json_response({"ok": False, "error": "name required"}, status=400)
            ok = self._provider_reset_action(name)
            if asyncio.iscoroutine(ok):
                ok = await ok
            return web.json_response({"ok": bool(ok)})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # -- WebSocket + broadcast --

    async def _handle_ws(self, request: Any) -> Any:
        ws_response = web.WebSocketResponse()
        await ws_response.prepare(request)
        self._ws_clients.append(ws_response)
        try:
            async for msg in ws_response:
                pass
        finally:
            self._ws_clients.remove(ws_response)
        return ws_response

    async def _broadcast(self, data: dict[str, Any]) -> None:
        if not self._ws_clients:
            return
        payload = json.dumps(data)
        for ws_client in list(self._ws_clients):
            try:
                await ws_client.send_str(payload)
            except Exception:
                self._ws_clients.remove(ws_client)

    # -- Agent definition CRUD handlers --

    async def _handle_agent_def_list(self, request: Any) -> Any:
        if not self._agent_def_list:
            return web.json_response([])
        result = self._agent_def_list()
        if asyncio.iscoroutine(result):
            result = await result
        return web.json_response(result)

    async def _handle_agent_def_create(self, request: Any) -> Any:
        if not self._agent_def_create:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            result = self._agent_def_create(body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok") else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_def_update(self, request: Any) -> Any:
        if not self._agent_def_update:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            agent_id = request.match_info["agent_id"]
            body = await request.json()
            result = self._agent_def_update(agent_id, body)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_def_delete(self, request: Any) -> Any:
        if not self._agent_def_delete:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            agent_id = request.match_info["agent_id"]
            result = self._agent_def_delete(agent_id)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_def_spawn(self, request: Any) -> Any:
        if not self._agent_def_spawn:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            agent_id = request.match_info["agent_id"]
            result = self._agent_def_spawn(agent_id)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_def_despawn(self, request: Any) -> Any:
        if not self._agent_def_despawn:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            agent_id = request.match_info["agent_id"]
            result = self._agent_def_despawn(agent_id)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agents_running(self, request: Any) -> Any:
        if not self._agent_running:
            return web.json_response([])
        result = self._agent_running()
        if asyncio.iscoroutine(result):
            result = await result
        return web.json_response(result)

    async def _handle_agent_activity(self, request: Any) -> Any:
        if not self._agent_activity:
            return web.json_response([])
        limit = int(request.query.get("limit", "50"))
        result = self._agent_activity(limit)
        if asyncio.iscoroutine(result):
            result = await result
        return web.json_response(result)

    async def _handle_agent_memories(self, request: Any) -> Any:
        if not self._agent_memories:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            agent_name = str(request.match_info.get("agent_name", "")).strip()
            if not agent_name:
                return web.json_response({"ok": False, "error": "agent_name required"}, status=400)
            result = self._agent_memories(agent_name)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 404
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_delegate(self, request: Any) -> Any:
        if not self._agent_delegate:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            task = str(body.get("task", "")).strip()
            agent_name = str(body.get("agent_name", "")).strip()
            agent_names = [
                str(name).strip()
                for name in body.get("agent_names", [])
                if str(name).strip()
            ]
            if not task or (not agent_name and not agent_names):
                return web.json_response({"ok": False, "error": "task and target agent required"}, status=400)
            result = self._agent_delegate(body)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_shared_task_create(self, request: Any) -> Any:
        if not self._shared_task_create:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            agents = body.get("agents", [])
            if not agents:
                return web.json_response({"ok": False, "error": "agents list required"}, status=400)
            result = self._shared_task_create(agents)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_shared_task_get(self, request: Any) -> Any:
        if not self._shared_task_get:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            task_id = request.match_info["task_id"]
            result = self._shared_task_get(task_id)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_auto_route(self, request: Any) -> Any:
        if not self._agent_auto_route:
            return web.json_response({"ok": False, "error": "Auto-routing not available"}, status=503)
        try:
            body = await request.json()
            result = self._agent_auto_route(body)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_consensus(self, request: Any) -> Any:
        if not self._agent_consensus:
            return web.json_response({"ok": False, "error": "Consensus not available"}, status=503)
        try:
            body = await request.json()
            result = self._agent_consensus(body)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_agent_pipeline(self, request: Any) -> Any:
        if not self._agent_pipeline:
            return web.json_response({"ok": False, "error": "Pipeline delegation not available"}, status=503)
        try:
            body = await request.json()
            result = self._agent_pipeline(body)
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # -- Workflow handlers --

    async def _handle_workflow_list(self, request: Any) -> Any:
        if not self._workflow_list_action:
            return web.json_response([])
        result = self._workflow_list_action()
        if asyncio.iscoroutine(result):
            result = await result
        return web.json_response(result)

    async def _handle_workflow_create(self, request: Any) -> Any:
        if not self._workflow_create_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            body = await request.json()
            result = self._workflow_create_action(body)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_workflow_run(self, request: Any) -> Any:
        if not self._workflow_run_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            workflow_id = str(request.match_info.get("workflow_id", "")).strip()
            result = self._workflow_run_action(workflow_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_workflow_pause(self, request: Any) -> Any:
        if not self._workflow_pause_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            workflow_id = str(request.match_info.get("workflow_id", "")).strip()
            result = self._workflow_pause_action(workflow_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 400
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_workflow_delete(self, request: Any) -> Any:
        if not self._workflow_delete_action:
            return web.json_response({"ok": False, "error": "Not available"}, status=503)
        try:
            workflow_id = str(request.match_info.get("workflow_id", "")).strip()
            result = self._workflow_delete_action(workflow_id)
            if asyncio.iscoroutine(result):
                result = await result
            status = 200 if result.get("ok", False) else 404
            return web.json_response(result, status=status)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # -- Database BI handlers --

    async def _handle_db_connections(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            config = load_config()
            saved = config.database_bi.saved_connections if getattr(config, "database_bi", None) else {}
            conns = []
            for name, conn in _dbi._connections.items():
                tables = conn._meta_cache.get("tables", [])
                dsn_display = str(conn.dsn)
                if "@" in dsn_display:
                    dsn_display = dsn_display.split("@", 1)[1]
                conns.append({
                    "name": name,
                    "driver": conn.driver,
                    "schema": conn.schema,
                    "read_only": conn.read_only,
                    "table_count": len(tables),
                    "connected": conn._conn is not None,
                    "persisted": name in saved,
                    "dsn_display": dsn_display,
                })
            return web.json_response(conns)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_db_connect(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            body = await request.json()
            result = await _dbi.db_connect(
                name=body.get("name", ""),
                driver=body.get("driver", ""),
                dsn=body.get("dsn", ""),
                schema=body.get("schema", ""),
                read_only=body.get("read_only", True),
            )
            ok = "Connected" in result
            if ok:
                config = load_config()
                saved = dict(getattr(config.database_bi, "saved_connections", {}) or {})
                saved[body.get("name", "")] = {
                    "driver": body.get("driver", ""),
                    "dsn": body.get("dsn", ""),
                    "schema": body.get("schema", ""),
                    "read_only": body.get("read_only", True),
                }
                update_config({
                    "database_bi": {
                        "saved_connections": saved,
                    },
                })
            return web.json_response({"ok": ok, "message": result, "persisted": ok})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_disconnect(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            body = await request.json()
            result = await _dbi.db_disconnect(name=body.get("name", ""))
            name = str(body.get("name", "") or "").strip()
            if name:
                config = load_config()
                saved = dict(getattr(config.database_bi, "saved_connections", {}) or {})
                if name in saved:
                    saved.pop(name, None)
                    update_config({"database_bi": {"saved_connections": saved}})
            return web.json_response({"ok": True, "message": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_tables(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            conn_name = request.query.get("connection", "")
            result = await _dbi.db_list_tables(connection=conn_name)
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_describe(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            conn_name = request.match_info.get("connection", "")
            table = request.match_info.get("table", "")
            result = await _dbi.db_describe_table(connection=conn_name, table=table)
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_query(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            body = await request.json()
            result = await _dbi.db_query(
                connection=body.get("connection", ""),
                query=body.get("query", ""),
            )
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_natural_query(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            body = await request.json()
            result = await _dbi.db_natural_query(
                connection=body.get("connection", ""),
                question=body.get("question", ""),
                provider=body.get("provider", ""),
                model=body.get("model", ""),
                base_url=body.get("base_url", ""),
                allow_fallback=body.get("allow_fallback"),
            )
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_chart(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            body = await request.json()
            result = await _dbi.db_chart(
                connection=body.get("connection", ""),
                query=body.get("query", ""),
                chart_type=body.get("chart_type", "bar"),
                title=body.get("title", ""),
                x_column=body.get("x_column", ""),
                y_column=body.get("y_column", ""),
                group_column=body.get("group_column", ""),
                provider=body.get("provider", ""),
                model=body.get("model", ""),
                base_url=body.get("base_url", ""),
                allow_fallback=body.get("allow_fallback"),
            )
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_db_explain(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import database_bi as _dbi
            body = await request.json()
            result = await _dbi.db_explain_data(
                connection=body.get("connection", ""),
                question=body.get("question", ""),
                provider=body.get("provider", ""),
                model=body.get("model", ""),
                base_url=body.get("base_url", ""),
                allow_fallback=body.get("allow_fallback"),
            )
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_provider_models(self, request: Any) -> Any:
        """List available models from a specific provider."""
        provider_name = request.match_info.get("provider_name", "")
        endpoint = request.query.get("endpoint", "")
        api_key = request.query.get("api_key", "")

        # If no explicit API key in query, try config secrets
        if not api_key:
            try:
                cfg = self._config_provider() if self._config_provider else {}
                secrets = cfg.get("provider_secrets", {})
                if isinstance(secrets, dict):
                    api_key = str(secrets.get(provider_name, ""))
            except Exception:
                pass

        try:
            from neuralclaw.providers.local import LocalProvider
            from neuralclaw.providers.openai import OpenAIProvider
            from neuralclaw.providers.anthropic import AnthropicProvider
            from neuralclaw.providers.openrouter import OpenRouterProvider
            from neuralclaw.providers.proxy import ProxyProvider

            # Default endpoints per provider
            PROVIDER_ENDPOINTS: dict[str, str] = {
                "local": "http://localhost:11434/v1",
                "ollama": "http://localhost:11434/v1",
                "openai": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com",
                "openrouter": "https://openrouter.ai/api/v1",
                "google": "https://generativelanguage.googleapis.com/v1beta/openai",
                "xai": "https://api.x.ai/v1",
                "venice": "https://api.venice.ai/api/v1",
                "mistral": "https://api.mistral.ai/v1",
                "minimax": "https://api.minimax.chat/v1",
                "vercel": "https://ai-gateway.vercel.sh/v1",
                "meta": "http://localhost:11434/v1",  # Llama via local Ollama
            }

            provider = None
            resolved_endpoint = endpoint or PROVIDER_ENDPOINTS.get(provider_name, "")

            if provider_name in ("local", "ollama", "meta"):
                provider = LocalProvider(base_url=resolved_endpoint)
            elif provider_name == "openai":
                provider = OpenAIProvider(
                    api_key=api_key or "none",
                    base_url=resolved_endpoint,
                )
            elif provider_name == "anthropic":
                provider = AnthropicProvider(
                    api_key=api_key or "none",
                    base_url=resolved_endpoint,
                )
            elif provider_name == "openrouter":
                provider = OpenRouterProvider(
                    api_key=api_key or "none",
                    base_url=resolved_endpoint,
                )
            elif provider_name in ("google", "xai", "venice", "mistral", "minimax", "vercel"):
                # These all expose OpenAI-compatible /models endpoints
                provider = ProxyProvider(
                    base_url=resolved_endpoint,
                    api_key=api_key or "none",
                )
            elif provider_name == "proxy":
                if not endpoint:
                    return web.json_response({"models": [], "error": "endpoint required"})
                provider = ProxyProvider(base_url=endpoint, api_key=api_key)
            else:
                return web.json_response({"models": [], "error": f"Unknown provider: {provider_name}"})

            models = _normalize_provider_model_catalog(provider_name, await provider.list_models())
            return web.json_response({
                "models": models,
                "count": len(models),
                "provider": provider_name,
                "endpoint": resolved_endpoint,
            })
        except Exception as e:
            return web.json_response({"models": [], "error": str(e)}, status=500)

    async def _handle_provider_status(self, request: Any) -> Any:
        """Return connectivity status for all known providers."""
        import aiohttp

        cfg = self._config_provider() if self._config_provider else {}
        providers_cfg = cfg.get("providers", {}) if isinstance(cfg, dict) else {}
        primary = str(providers_cfg.get("primary", "local")) if isinstance(providers_cfg, dict) else "local"
        secrets = cfg.get("provider_secrets", {}) if isinstance(cfg, dict) else {}

        PROVIDER_ENDPOINTS: dict[str, str] = {
            "local": "http://localhost:11434/v1",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "openrouter": "https://openrouter.ai/api/v1",
            "google": "https://generativelanguage.googleapis.com/v1beta/openai",
            "xai": "https://api.x.ai/v1",
            "venice": "https://api.venice.ai/api/v1",
            "mistral": "https://api.mistral.ai/v1",
            "minimax": "https://api.minimax.chat/v1",
            "vercel": "https://ai-gateway.vercel.sh/v1",
            "meta": "http://localhost:11434/v1",
        }

        results = []
        for name, default_endpoint in PROVIDER_ENDPOINTS.items():
            prov_cfg = providers_cfg.get(name, {}) if isinstance(providers_cfg, dict) else {}
            endpoint = str(prov_cfg.get("base_url", "")) if isinstance(prov_cfg, dict) else ""
            endpoint = endpoint or default_endpoint
            has_key = bool(secrets.get(name)) if isinstance(secrets, dict) else False
            is_primary = (name == primary)

            # Quick connectivity check
            available = False
            try:
                test_url = f"{endpoint.rstrip('/')}/models"
                headers: dict[str, str] = {}
                key = str(secrets.get(name, "")) if isinstance(secrets, dict) else ""
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        test_url, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        available = resp.status in (200, 401, 403)
            except Exception:
                available = False

            results.append({
                "name": name,
                "endpoint": endpoint,
                "available": available,
                "has_key": has_key or name in ("local", "meta"),
                "is_primary": is_primary,
                "configured": bool(endpoint) and (has_key or name in ("local", "meta")),
            })

        return web.json_response({"providers": results, "primary": primary})

    # -- Workspace handlers --

    async def _handle_workspace_structure(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import framework_intel as _fi
            include_hidden = request.query.get("include_hidden", "false").lower() == "true"
            result = await _fi.list_workspace_structure(include_hidden=include_hidden)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_workspace_projects(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import project_scaffold as _ps
            result = await _ps.list_projects()
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_workspace_scaffold(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import project_scaffold as _ps
            body = await request.json()
            result = await _ps.scaffold_project(
                project_name=body.get("project_name", ""),
                template=body.get("template", "generic"),
                description=body.get("description", ""),
                author=body.get("author", ""),
                claim_directory=body.get("claim_directory", True),
            )
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_workspace_project_detail(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import project_scaffold as _ps
            name = request.match_info["name"]
            result = await _ps.get_project_info(project_name=name)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_workspace_project_add(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import project_scaffold as _ps
            name = request.match_info["name"]
            body = await request.json()
            result = await _ps.add_to_project(
                project_name=name,
                component=body.get("component", ""),
            )
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_workspace_claims(self, request: Any) -> Any:
        try:
            from neuralclaw.swarm.workspace_coordinator import WorkspaceCoordinator as _WC
            # Find the gateway's coordinator via the framework_intel module
            from neuralclaw.skills.builtins import framework_intel as _fi
            coord = _fi._workspace_coordinator
            if coord is None:
                return web.json_response([])
            claims = await coord.list_all_claims()
            return web.json_response([
                {
                    "claim_id": c.claim_id,
                    "agent_name": c.agent_name,
                    "path": c.path,
                    "purpose": c.purpose,
                    "claimed_at": c.claimed_at,
                    "expires_at": c.expires_at,
                }
                for c in claims
            ])
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_workspace_claim(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import framework_intel as _fi
            body = await request.json()
            result = await _fi.claim_workspace_dir(
                path=body.get("path", ""),
                purpose=body.get("purpose", ""),
            )
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def _handle_workspace_release(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import framework_intel as _fi
            body = await request.json()
            result = await _fi.release_workspace_dir(path=body.get("path", ""))
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # -- Skills handlers --

    async def _handle_skills_available(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import framework_intel as _fi
            source_filter = request.query.get("source_filter", "all")
            result = await _fi.list_available_skills(source_filter=source_filter)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_skills_template(self, request: Any) -> Any:
        try:
            from neuralclaw.skills.builtins import framework_intel as _fi
            skill_type = request.query.get("skill_type", "basic")
            result = await _fi.get_skill_template(skill_type=skill_type)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _periodic_push(self) -> None:
        while True:
            await asyncio.sleep(5)
            if not self._ws_clients:
                continue
            try:
                if self._stats_provider:
                    stats = self._stats_provider()
                    stats["uptime"] = self._format_uptime()
                    await self._broadcast({"type": "stats", "data": stats})
                if self._agents_provider:
                    await self._broadcast({"type": "agents", "data": self._agents_provider()})
                if self._federation_provider:
                    await self._broadcast({"type": "federation", "data": self._federation_provider()})
                if self._memory_provider:
                    mem = self._memory_provider()
                    if asyncio.iscoroutine(mem):
                        mem = await mem
                    await self._broadcast({"type": "memory", "data": mem})
                if self._bus_provider:
                    await self._broadcast({"type": "bus", "data": self._bus_provider()})
            except Exception:
                pass

    def _format_uptime(self) -> str:
        elapsed = int(time.time() - self._start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m {seconds}s"
