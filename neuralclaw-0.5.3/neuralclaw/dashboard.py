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
import time
from typing import Any

try:
    from aiohttp import web
except ImportError:
    web = None  # type: ignore


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
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self._host = host
        self._port = port
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
        self._bus_provider: Any = None

        # Action callables
        self._spawn_action: Any = None
        self._despawn_action: Any = None
        self._send_message_action: Any = None
        self._join_federation_action: Any = None
        self._clear_memory_action: Any = None
        self._get_features_action: Any = None
        self._set_feature_action: Any = None
        self._message_peer_action: Any = None

    # -- Data provider setters --

    def set_stats_provider(self, provider: Any) -> None:
        self._stats_provider = provider

    def set_agents_provider(self, provider: Any) -> None:
        self._agents_provider = provider

    def set_federation_provider(self, provider: Any) -> None:
        self._federation_provider = provider

    def set_memory_provider(self, provider: Any) -> None:
        self._memory_provider = provider

    def set_bus_provider(self, provider: Any) -> None:
        self._bus_provider = provider

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

    def set_features_provider(self, getter: Any, setter: Any) -> None:
        self._get_features_action = getter
        self._set_feature_action = setter

    def set_message_peer_action(self, action: Any) -> None:
        self._message_peer_action = action

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

        self._app = web.Application()
        # GET routes
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/api/stats", self._handle_stats)
        self._app.router.add_get("/api/traces", self._handle_traces)
        self._app.router.add_get("/api/agents", self._handle_agents)
        self._app.router.add_get("/api/federation", self._handle_federation)
        self._app.router.add_get("/api/memory", self._handle_memory)
        self._app.router.add_get("/api/bus", self._handle_bus)
        self._app.router.add_get("/api/features", self._handle_get_features)
        self._app.router.add_get("/ws/traces", self._handle_ws)
        # POST routes
        self._app.router.add_post("/api/spawn", self._handle_spawn)
        self._app.router.add_post("/api/despawn", self._handle_despawn)
        self._app.router.add_post("/api/message", self._handle_message)
        self._app.router.add_post("/api/federation/join", self._handle_federation_join)
        self._app.router.add_post("/api/memory/clear", self._handle_memory_clear)
        self._app.router.add_post("/api/features", self._handle_set_feature)
        self._app.router.add_post("/api/federation/message", self._handle_message_peer)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        self._push_task = asyncio.create_task(self._periodic_push())
        print(f"[Dashboard] Running at http://localhost:{self._port}")

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
        stats["uptime"] = self._format_uptime()
        return web.json_response(stats)

    async def _handle_traces(self, request: Any) -> Any:
        limit = int(request.query.get("limit", "50"))
        return web.json_response(self._traces[-limit:])

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

    async def _handle_bus(self, request: Any) -> Any:
        data = self._bus_provider() if self._bus_provider else []
        return web.json_response(data)

    async def _handle_get_features(self, request: Any) -> Any:
        features = self._get_features_action() if self._get_features_action else {}
        return web.json_response(features)

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
            response = self._send_message_action(content)
            if asyncio.iscoroutine(response):
                response = await response
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
            result = self._clear_memory_action()
            if asyncio.iscoroutine(result):
                result = await result
            return web.json_response({"ok": True, **result})
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
            ok = self._set_feature_action(feature, value)
            return web.json_response({"ok": bool(ok)})
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
