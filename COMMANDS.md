# NeuralClaw — Complete Commands Reference
> Every command you'll ever need, from install to production.

---

## Installation

```bash
# Install from PyPI
pip install neuralclaw

# Install with all channel adapters (Telegram, Discord, Slack)
pip install neuralclaw[all-channels]

# Install a specific channel only
pip install neuralclaw[telegram]
pip install neuralclaw[discord]
pip install neuralclaw[slack]

# Install from source (development)
git clone https://github.com/placeparks/neuralclaw.git
cd neuralclaw
pip install -e ".[dev]"
```

---

## First-Time Setup

```bash
# Interactive setup wizard — configures LLM provider + stores API keys in OS keychain
neuralclaw init

# Start chatting immediately
neuralclaw chat

# Chat with a specific provider
neuralclaw chat --provider openai
neuralclaw chat --provider anthropic
neuralclaw chat --provider openrouter
neuralclaw chat --provider local       # Ollama on localhost:11434
```

---

## Core Commands

```bash
neuralclaw init                  # Setup wizard (LLM providers + API keys)
neuralclaw chat                  # Interactive terminal chat
neuralclaw chat --provider X     # Chat using a specific provider
neuralclaw gateway               # Start full gateway (all channels + cognitive pipeline)
neuralclaw status                # Show config, providers, channels, and health
neuralclaw doctor                # Diagnose all subsystems (config, providers, channels, DB)
neuralclaw repair                # Fix common issues automatically
neuralclaw --version             # Show version
neuralclaw --help                # Show all available commands
```

### Gateway Options

```bash
neuralclaw gateway                                        # Start with defaults
neuralclaw gateway --name "Agent-2"                       # Custom node name
neuralclaw gateway --federation-port 8101                 # Override federation port
neuralclaw gateway --dashboard-port 8081                  # Override dashboard port
neuralclaw gateway --web-port 8082                        # Override web chat port
neuralclaw gateway --seed http://192.168.1.50:8100        # Auto-join a seed node
```

| Option | Description | Default |
|--------|-------------|---------|
| `--name` | Override node name (shown in federation) | Config `general.name` |
| `--federation-port` | Federation HTTP port | `8100` |
| `--dashboard-port` | Dashboard web UI port | `8080` |
| `--web-port` | Web chat interface port | `8081` |
| `--seed` | Seed node URL to auto-join on startup | None |

**Run multiple instances** for local federation testing:
```bash
# Terminal 1 — primary node
neuralclaw gateway

# Terminal 2 — second node, different ports, joins first
neuralclaw gateway --name "Agent-2" --federation-port 8101 --dashboard-port 8081 --web-port 8082 --seed http://localhost:8100
```

---

## Proxy Provider (ChatGPT / Claude Subscription Access)

Use your existing ChatGPT Plus or Claude Pro subscription with NeuralClaw
by routing through a self-hosted reverse proxy.

```bash
neuralclaw proxy setup           # Guided wizard — configure proxy URL, model, API key
neuralclaw proxy status          # Show proxy config + live connectivity check
```

### Step-by-Step: Use Your ChatGPT Subscription

1. **Set up a reverse proxy** on your machine. Pick one:

   | Proxy | What it does | Install |
   |-------|-------------|---------|
   | **chatgpt-to-api** | Converts your ChatGPT Plus browser session into an OpenAI-compatible API | `docker run -p 3040:3040 xqdoo00o/chatgpt-to-api` |
   | **one-api / new-api** | Multi-provider gateway (ChatGPT, Claude, Gemini, etc.) | `docker run -p 3000:3000 justsong/one-api` |
   | **LiteLLM** | Proxy 100+ LLMs with OpenAI-compatible endpoint | `pip install litellm && litellm --model gpt-4` |
   | **LobeChat** | Self-hosted AI gateway with web UI | See LobeChat docs |

2. **Configure NeuralClaw** to point at your proxy:

   ```bash
   neuralclaw proxy setup
   ```

   It will ask:
   - **Base URL**: The `/v1` endpoint (e.g. `http://localhost:3040/v1`)
   - **Model**: The model name your proxy serves (e.g. `gpt-4`, `gpt-4o`)
   - **API key**: Optional — depends on your proxy's auth (Enter to skip)
   - **Set as primary?**: Say `y` to route all NeuralClaw traffic through it

3. **Start chatting**:

   ```bash
   neuralclaw chat                 # Uses your primary provider
   neuralclaw chat --provider proxy  # Explicitly use proxy
   ```

### Step-by-Step: Use Your Claude Pro Subscription

Same flow — just use a Claude-compatible reverse proxy:

1. Set up **fuclaude** or **new-api** with your Claude session cookie
2. Run `neuralclaw proxy setup`
3. Enter the proxy URL and model (e.g. `claude-sonnet-4-20250514`)
4. Set as primary → start chatting

### Manual Config (Alternative)

Edit `~/.neuralclaw/config.toml` directly:

```toml
[providers]
primary = "proxy"

[providers.proxy]
model = "gpt-4o"
base_url = "http://localhost:3040/v1"
```

If your proxy needs an API key:
```bash
# Store in OS keychain (never in plaintext)
python -c "from neuralclaw.config import set_api_key; set_api_key('proxy', 'your-key-here')"
```

---

## Channel Management

```bash
neuralclaw channels setup          # Guided setup for all channels
neuralclaw channels list           # List configured channels and their status
neuralclaw channels test [name]    # Test channel connectivity (all or specific)
neuralclaw channels add <name>     # Add a channel interactively
neuralclaw channels remove <name>  # Remove a channel's credentials
neuralclaw channels connect whatsapp  # WhatsApp QR pairing (interactive)
```

### Telegram
1. Message **@BotFather** on Telegram → `/newbot` → copy the token
2. `neuralclaw channels setup` → paste token for Telegram
3. `neuralclaw channels test telegram` → verify connectivity
4. `neuralclaw gateway` → message your bot

### Discord
1. [discord.com/developers](https://discord.com/developers/applications) → New App → Bot → Copy token
2. Enable **Message Content Intent** in Bot settings
3. Invite bot to server with Messages scope
4. `neuralclaw channels setup` → paste token
5. `neuralclaw channels test discord` → verify connectivity
6. `neuralclaw gateway`

### Slack
1. Create app at [api.slack.com/apps](https://api.slack.com/apps) → Enable Socket Mode
2. Get Bot Token (`xoxb-...`) and App-Level Token (`xapp-...`)
3. `neuralclaw channels setup` → paste both tokens
4. `neuralclaw gateway`

### WhatsApp

WhatsApp connects via QR code scan — no token needed.

**Only prerequisite: Node.js >= 18**
```bash
# Install Node.js from https://nodejs.org
node --version   # Should show v18 or higher
```

That's it. All npm dependencies (`@whiskeysockets/baileys`, `@hapi/boom`) are **automatically installed** into `~/.neuralclaw/bridge/` on first use — no manual `npm install` needed.

**Connect:**
```bash
neuralclaw channels connect whatsapp
```

This will:
1. Auto-install bridge dependencies (first run only, takes ~30s)
2. Start the WhatsApp bridge
3. Display a QR code in your terminal
4. Scan it with your phone (WhatsApp → Linked Devices → Link a Device)
5. On success: auth is saved, WhatsApp is enabled in config
6. Run `neuralclaw gateway` to start receiving messages

**Troubleshooting:**
- "Node.js not found" → Install from https://nodejs.org
- "npm install failed" → Check your internet connection; ensure npm is in PATH
- "Bridge crashed on startup" → Check Node.js version is >= 18
- QR not appearing → Run the command again; check stderr output for errors

---

## Agent Skills — GitHub Repos, Script Execution & API Client

NeuralClaw agents can clone GitHub repos, install their dependencies, run scripts,
and make authenticated API calls — all through natural language on any channel.

### GitHub Repository Management

The agent can clone, install, list, and remove repos when asked by a user:

| Tool | Description |
|------|-------------|
| `clone_repo` | Clone a GitHub/GitLab/Bitbucket repo (HTTPS, shallow clone) |
| `install_repo_deps` | Auto-detect and install dependencies (Python venv, npm, Cargo, Go) |
| `list_repos` | List all managed repos with dependency status |
| `remove_repo` | Remove a cloned repo |

**Example conversation:**
> **User:** Clone https://github.com/pallets/flask and install its deps
> **Agent:** Cloned flask into ~/.neuralclaw/workspace/repos/pallets_flask.
> Detected requirements.txt — installing Python dependencies in a virtual environment...
> Dependencies installed successfully.

**Security:**
- Only HTTPS URLs from allowed hosts (github.com, gitlab.com, bitbucket.org)
- Shallow clones (`--depth 1`) by default
- No embedded credentials in URLs
- All repos stored in `~/.neuralclaw/workspace/repos/`

### Script Execution

| Tool | Description |
|------|-------------|
| `run_repo_script` | Run a script (.py/.js/.sh/.ts) with auto-detected runtime |
| `run_repo_command` | Run a command in a repo's environment (allowlisted executables) |

**Example:**
> **User:** Run the tests in the flask repo
> **Agent:** Running `python -m pytest` in pallets_flask... [output]

**Security:**
- Gated by `deny_shell_execution` policy (default: **denied**)
- To enable: set `deny_shell_execution = false` in `~/.neuralclaw/config.toml`
- Command allowlist: `python`, `node`, `npm`, `cargo`, `go`, `bash`, `pip`, `pytest`, `make`
- Blocked: `rm -rf`, `sudo`, `curl`, `wget`, `nc`, `ssh`, pipe-to-shell
- Timeout enforcement (default 60s, max 300s)

### API Client

| Tool | Description |
|------|-------------|
| `api_request` | Make an authenticated HTTP request (GET/POST/PUT/DELETE/PATCH) |
| `save_api_config` | Save an API config with keychain-stored credentials |
| `list_api_configs` | List saved API configs (keys never shown) |

**Auth types:** `bearer`, `api_key_header`, `api_key_query`, `basic`

**Example:**
> **User:** Save my OpenWeather API with key abc123, then get the weather in London
> **Agent:** Saved API config 'openweather'. Making request...
> Current weather in London: 12C, partly cloudy.

**Security:**
- All requests validated against SSRF policy (private IPs, cloud metadata blocked)
- API keys stored in OS keychain, never in config.toml
- Response bodies capped at 50,000 characters

### Config Reference

```toml
# ~/.neuralclaw/config.toml

[workspace]
repos_dir = "~/.neuralclaw/workspace/repos"
max_repo_size_mb = 500
allowed_git_hosts = ["github.com", "gitlab.com", "bitbucket.org"]
max_clone_timeout_seconds = 120
max_install_timeout_seconds = 300
max_exec_timeout_seconds = 300

[policy]
# Must set to false to enable script execution
deny_shell_execution = false

# New tools are included in the default allowed_tools list
# You can restrict by removing specific tools
```

---

## Doctor & Repair

```bash
neuralclaw doctor                  # Diagnose all subsystems
neuralclaw doctor --json           # Output as JSON (for scripting)
neuralclaw repair                  # Fix issues automatically
neuralclaw repair --dry-run        # Show what would be fixed without changing anything
neuralclaw repair --no-backup      # Repair without backing up config first
```

Doctor checks:
- Directory structure (config, data, logs)
- Config file validity
- Provider API keys
- Channel tokens and connectivity
- Memory database integrity
- Log directory size

Repair can fix:
- Missing directories
- Corrupt config (backup + restore defaults)
- Corrupt database (backup + remove, re-created on next run)
- Oversized log files (truncate)

---

## Monitoring & Dashboard

```bash
neuralclaw gateway               # Dashboard starts automatically at http://localhost:8080
neuralclaw status                # Quick config/provider/channel health check
```

The dashboard is an interactive SPA embedded in the gateway. It refreshes every 5 seconds via WebSocket.

### Dashboard Panels

| Panel | Shows | Interactive Controls |
|-------|-------|---------------------|
| **System Status** | LLM provider, uptime, message count | Feature toggle switches |
| **Swarm Agents** | Agent chips with source/capabilities | Spawn Agent, Despawn (x) |
| **Federation Nodes** | Peer table: name, status, trust, caps | Join Peer, Message Peer |
| **Memory Health** | Episodic/semantic/procedural counts | Clear All Memory |
| **Send Test Message** | Full-width input + response display | Send through cognitive pipeline |
| **Live Traces** | Reasoning traces with filter/search | Filter by level, keyword search |
| **Event Bus Log** | NeuralBus event stream | Auto-scroll |

### Dashboard API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Dashboard HTML |
| `/api/status` | GET | System status JSON |
| `/api/agents` | GET | Swarm agent list |
| `/api/federation` | GET | Federation node list |
| `/api/memory` | GET | Memory store counts |
| `/api/bus` | GET | Recent bus events |
| `/api/traces` | GET | Reasoning trace log |
| `/api/features` | GET | Feature toggle states |
| `/api/spawn` | POST | Spawn a remote agent |
| `/api/despawn` | POST | Remove an agent |
| `/api/message` | POST | Send test message through pipeline |
| `/api/federation/join` | POST | Join a federation peer |
| `/api/federation/message` | POST | Send message to a specific peer |
| `/api/memory/clear` | POST | Clear all memory stores |
| `/api/features` | POST | Toggle a feature on/off |
| `/ws` | WS | Live data push (5s interval) |

---

## Swarm Intelligence

```bash
neuralclaw swarm status          # View mesh status (total agents, online agents, messages)
neuralclaw swarm spawn <name>    # Spawn a new agent on the swarm mesh
```

### Spawn Agent Options

```bash
neuralclaw swarm spawn researcher -c "search,analysis"          # Local agent with capabilities
neuralclaw swarm spawn remote-agent -e http://peer:8100          # Remote agent via endpoint
neuralclaw swarm spawn analyst -c "data,stats" -d "Data analyst" # With description
```

| Option | Short | Description |
|--------|-------|-------------|
| `--capabilities` | `-c` | Comma-separated capability tags (default: `general`) |
| `--description` | `-d` | Agent description |
| `--endpoint` | `-e` | Remote agent endpoint URL (omit for local) |

> **Note:** The CLI spawn command is informational. At runtime, agents are
> spawned programmatically via `gateway.spawner.spawn_local()` or
> `gateway.spawner.spawn_remote()`.

### Python API — Agent Spawner

```python
from neuralclaw.swarm.spawn import AgentSpawner, SpawnedAgent
from neuralclaw.swarm.mesh import AgentMesh, MeshMessage
from neuralclaw.swarm.delegation import DelegationChain, DelegationContext

mesh = AgentMesh()
chain = DelegationChain()
spawner = AgentSpawner(mesh, chain)

# Spawn a local agent (registers in both mesh and delegation)
async def handler(msg: MeshMessage) -> MeshMessage | None:
    return msg.reply(f"Analyzed: {msg.content}", payload={"confidence": 0.9})

agent = spawner.spawn_local(
    name="analyst",
    description="Data analysis specialist",
    capabilities=["analysis", "statistics"],
    handler=handler,
)

# Spawn a remote agent (proxy handler forwards via HTTP)
agent = spawner.spawn_remote(
    name="remote-researcher",
    description="Remote research agent",
    capabilities=["search", "research"],
    endpoint="http://192.168.1.100:8100",
)

# Use spawned agent via delegation
result = await chain.delegate("analyst", DelegationContext(task_description="Analyze Q4 data"))

# Use spawned agent via mesh messaging
response = await mesh.send(from_agent="coordinator", to_agent="analyst", content="Run analysis")

# Despawn an agent (removes from mesh + delegation)
spawner.despawn("analyst")

# View all spawned agents
for info in spawner.get_status():
    print(f"  {info['name']} [{info['source']}] — {info['capabilities']}")
```

### Python API — Delegation & Consensus

```python
from neuralclaw.swarm.delegation import DelegationChain, DelegationContext
from neuralclaw.swarm.consensus import ConsensusProtocol, ConsensusStrategy
from neuralclaw.swarm.mesh import AgentMesh

# Delegate tasks to specialists
chain = DelegationChain()
ctx = DelegationContext(task_description="Research topic X", max_steps=10)
result = await chain.delegate("researcher", ctx)

# Remove an agent executor
chain.unregister_executor("researcher")

# Multi-agent consensus on high-stakes decisions
consensus = ConsensusProtocol(chain)
result = await consensus.seek_consensus("Should we deploy?", strategy=ConsensusStrategy.MAJORITY_VOTE)

# Agent mesh — register and discover agents
mesh = AgentMesh()
mesh.register("analyst", "Data analysis", ["research", "data"], handler)
agents = mesh.discover(capability="research")
```

---

## Federation

```bash
neuralclaw federation            # Show live federation status (connected nodes, trust scores)
neuralclaw federation --port 9000  # Query federation on a custom port
```

When the gateway is running, `neuralclaw federation` queries the live
`/federation/status` endpoint and displays a table of connected nodes with
their name, status, trust score, capabilities, and endpoint. If the server
is not running, it falls back to showing protocol info.

### Gateway Integration

Federation starts automatically with the gateway when `features.swarm = true`
and `federation.enabled = true` in config:

```bash
neuralclaw gateway
# Output includes:
#   Federation: port 8100, seeds: ['none']
#   Spawner: 0 agents
```

Configure seed nodes in `~/.neuralclaw/config.toml`:

```toml
[federation]
enabled = true
port = 8100
bind_host = "0.0.0.0"           # Use 0.0.0.0 for LAN/remote access
seed_nodes = ["http://192.168.1.50:8100"]  # Peers to auto-join on startup
heartbeat_interval = 60
node_name = ""  # Defaults to general.name
```

The gateway will:
1. Start the federation HTTP server on the configured port
2. Join all seed nodes automatically
3. Run a heartbeat loop to keep peers alive
4. Sync federation peers into the mesh as `fed:<name>` agents (via FederationBridge)
5. Route incoming task messages through the full cognitive pipeline
6. Return pipeline responses back to the requesting node

### Cross-Node Messaging

When Node A sends a message to Node B:
1. Node A POSTs to `http://NodeB:8100/federation/message`
2. Node B's federation handler receives the message
3. If `message_type == "task"`, it runs through `process_message()` (the full cognitive pipeline: perception → threat screen → memory → reasoning → action)
4. The pipeline response is returned to Node A

This means federated agents think with their full brain — they don't just relay text, they reason about it.

**From the dashboard**: Click "Message" next to any federation node, type a message, and the peer's cognitive pipeline will process it and return a response.

**From code**:
```python
# Send a message to a peer node
reply = await federation.send_message(
    target_node_id="node-abc123",
    content="What do you know about quantum computing?",
    message_type="task",
)
print(reply.content)  # Full pipeline-processed response
```

### Connecting Agents on Different Machines

#### Step 1: Configure Machine A (seed node)
```toml
# ~/.neuralclaw/config.toml on Machine A (192.168.1.10)
[general]
name = "Alpha"

[federation]
enabled = true
port = 8100
bind_host = "0.0.0.0"   # IMPORTANT: bind to all interfaces for LAN access
seed_nodes = []
```

```bash
# Start the gateway
neuralclaw gateway
```

#### Step 2: Configure Machine B (joins Machine A)
```toml
# ~/.neuralclaw/config.toml on Machine B (192.168.1.20)
[general]
name = "Beta"

[federation]
enabled = true
port = 8100
bind_host = "0.0.0.0"
seed_nodes = ["http://192.168.1.10:8100"]   # Machine A's IP
```

```bash
# Start — auto-joins Machine A
neuralclaw gateway
```

Or use CLI flags without editing config:
```bash
neuralclaw gateway --name "Beta" --seed http://192.168.1.10:8100
```

#### Step 3: Verify
- Machine A's dashboard (`http://192.168.1.10:8080`) shows `Beta` in Federation Nodes
- Machine B's dashboard (`http://192.168.1.20:8080`) shows `Alpha` in Federation Nodes
- Both show `fed:Alpha` / `fed:Beta` in Swarm Agents
- Click "Message" in the federation table to send a cross-node message

#### Step 4: Add more machines
Each new machine only needs one seed — it discovers all existing peers through that seed:
```bash
# Machine C — joins via Machine A, auto-discovers Machine B too
neuralclaw gateway --name "Gamma" --seed http://192.168.1.10:8100
```

#### Network Requirements
- All machines must be able to reach each other on their federation ports (default `8100`)
- Open firewall port `8100` (and `8080` for dashboard access)
- For internet/cloud: use public IPs or set up port forwarding
- `bind_host` must be `"0.0.0.0"` (not `"127.0.0.1"`) for remote access

### Python API — Federation

```python
from neuralclaw.swarm.federation import FederationProtocol, FederationBridge

# Manual federation setup
fed = FederationProtocol(node_name="my-agent", port=8100)
await fed.start()                                  # Start federation HTTP server
await fed.join_federation("http://peer:8100")       # Connect to another agent
await fed.send_message(node_id, "Analyze this")     # Cross-network task
await fed.broadcast("Status check?")                # Broadcast to all peers
await fed.send_heartbeats()                          # Keep peers alive
await fed.stop()                                     # Shutdown

# Set a handler so incoming messages go through your pipeline
fed.set_message_handler(my_async_handler)

# Federation bridge — auto-sync federation peers to mesh
bridge = FederationBridge(federation=fed, spawner=spawner)
await bridge.start(sync_interval=30.0)  # Periodically sync peers → mesh agents
bridge.sync()                            # One-shot sync
await bridge.stop()
```

### Federation Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/federation/discover` | POST | Exchange node cards |
| `/federation/message` | POST | Send a task/message (processed by cognitive pipeline) |
| `/federation/heartbeat` | POST | Health check |
| `/federation/status` | GET | View all nodes |

---

## Benchmarks

```bash
neuralclaw benchmark                        # Run full suite (5 categories)
neuralclaw benchmark --category perception  # Perception pipeline only
neuralclaw benchmark --category memory      # Memory store + search
neuralclaw benchmark --category security    # Threat screening accuracy
neuralclaw benchmark --category reasoning   # Intent classification
neuralclaw benchmark --category latency     # Neural bus event throughput
neuralclaw benchmark --export               # Export results to JSON
```

---

## Migration

```bash
neuralclaw migrate                          # Auto-detect and migrate from OpenClaw
neuralclaw migrate --source /path/to/old    # Specify source directory manually
neuralclaw migrate --dry-run                # Scan only, don't change anything
```

Supports migration from: **OpenClaw**, **Clawdbot**, **Moltbot**

---

## Marketplace & Economy

### Python API
```python
from neuralclaw.skills.marketplace import SkillMarketplace
from neuralclaw.skills.economy import SkillEconomy

# Publish a skill (with Ed25519 signing + static analysis)
mp = SkillMarketplace()
pkg, findings = mp.publish("my_skill", "1.0", "author", "Description", code, private_key)

# Install a skill
mp.install("web_search")

# Economy — credits, ratings, leaderboards
econ = SkillEconomy()
econ.register_author("mirac", "Mirac")
econ.register_skill("web_search", "mirac")
econ.record_usage("web_search", user_id="u1", success=True)
econ.rate_skill("web_search", rater_id="u1", score=4.5, review="Excellent!")
print(econ.get_trending())
print(econ.get_author_leaderboard())
```

---

## API Key Management

```bash
# Keys are stored in your OS keychain (never in plaintext files)
# You can also use environment variables:
set OPENAI_API_KEY=sk-...
set ANTHROPIC_API_KEY=sk-ant-...
set OPENROUTER_API_KEY=sk-or-...

# Check what's configured
neuralclaw status
```

### Python API
```python
from neuralclaw.config import get_api_key, set_api_key

get_api_key("openai")                    # Read from keychain
set_api_key("telegram", "BOT_TOKEN")     # Store in keychain
```

---

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run full test suite (269 tests)
python -m pytest tests/ -v

# Run specific test modules
python -m pytest tests/test_perception.py -v
python -m pytest tests/test_memory.py -v
python -m pytest tests/test_evolution_security_swarm.py -v
python -m pytest tests/test_federation_spawn.py -v
python -m pytest tests/test_ssrf.py -v
python -m pytest tests/test_sandbox_policy.py -v
python -m pytest tests/test_proxy_provider.py -v
python -m pytest tests/test_proxy_setup.py -v
python -m pytest tests/test_health.py -v
python -m pytest tests/test_config_validation.py -v
python -m pytest tests/test_toolcall_and_baileys.py -v
python -m pytest tests/test_github_repos.py -v
python -m pytest tests/test_repo_exec.py -v
python -m pytest tests/test_api_client.py -v

# Run with coverage
python -m pytest tests/ --cov=neuralclaw --cov-report=term-missing

# Lint
ruff check neuralclaw/
ruff format neuralclaw/
```

---

## Debugging

```bash
# Check if gateway initializes correctly
python -c "
import asyncio
from neuralclaw.gateway import NeuralClawGateway
async def t():
    gw = NeuralClawGateway()
    await gw.initialize()
    print(f'Provider: {gw._provider.name if gw._provider else \"NONE\"}')
    print(f'Skills: {gw._skills.count}')
    print(f'Spawner: {gw.spawner.count if gw.spawner else \"disabled\"} agents')
    await gw.stop()
asyncio.run(t())
"

# Quick import smoke test
python -c "from neuralclaw.gateway import NeuralClawGateway; print('OK')"

# Verify swarm imports
python -c "from neuralclaw.swarm import FederationProtocol, AgentSpawner; print('OK')"

# List all stored keychain keys
python -c "
from neuralclaw.config import get_api_key
for k in ['openai','anthropic','openrouter','telegram','discord','slack_bot','slack_app']:
    v = get_api_key(k)
    status = f'set ({v[:8]}...)' if v else 'not set'
    print(f'  {k:15s} {status}')
"

# Troubleshooting: 'neuralclaw' not recognized
# Add Python Scripts to PATH, or use:
python -m neuralclaw.cli chat
```

---

## Git & Publishing

```bash
# Push changes
git add -A && git commit -m "message" && git push

# Build package for PyPI
pip install build twine
python -m build

# Publish to PyPI
python -m twine upload dist/*

# Publish to TestPyPI first (recommended)
python -m twine upload --repository testpypi dist/*
```

---

## Architecture Quick Reference

```
Gateway (brain)
├── Perception: Intake → Threat Screen → Classify
├── Memory: Episodic + Semantic + Procedural + Metabolism
├── Reasoning: Fast Path → Deliberative → Reflective → Meta-Cognitive
├── Action: Sandbox + Capabilities + Audit
├── Evolution: Calibrator + Distiller + Synthesizer
├── Swarm: Delegation + Consensus + Mesh + Federation + Spawner
├── Economy: Credits + Ratings + Leaderboard
└── Bus: Neural Bus (async pub/sub) + Telemetry
```

### Key Files
| File | Purpose |
|------|---------|
| `gateway.py` | Main orchestration engine |
| `cli.py` | All CLI commands (init, chat, gateway, proxy, channels, doctor, repair) |
| `config.py` | Config loading + OS keychain secrets + update_config() |
| `health.py` | Doctor diagnostics + repair engine |
| `dashboard.py` | Interactive web dashboard (SPA + WebSocket) |
| `benchmark.py` | Performance benchmark suite |
| `bus/neural_bus.py` | Async event backbone |
| `cortex/perception/` | Intake, classifier, threat screening |
| `cortex/memory/` | Episodic, semantic, procedural, metabolism |
| `cortex/reasoning/` | Fast-path, deliberative, reflective, meta-cognitive |
| `cortex/action/` | Sandbox, capabilities, policy, network, audit |
| `cortex/evolution/` | Calibrator, distiller, synthesizer |
| `providers/proxy.py` | Reverse proxy provider (ChatGPT/Claude session access) |
| `providers/openai.py` | OpenAI provider (base for proxy) |
| `providers/anthropic.py` | Anthropic provider |
| `providers/router.py` | Provider router with circuit breaker |
| `swarm/delegation.py` | Task delegation chains |
| `swarm/consensus.py` | Multi-agent voting |
| `swarm/mesh.py` | Agent-to-agent communication |
| `swarm/federation.py` | Cross-network federation + FederationBridge |
| `swarm/spawn.py` | Dynamic agent spawning (AgentSpawner) |
| `skills/marketplace.py` | Signed skill distribution |
| `skills/economy.py` | Marketplace economy |
| `channels/telegram.py` | Telegram adapter |
| `channels/discord_adapter.py` | Discord adapter |
| `channels/slack.py` | Slack adapter |
| `channels/whatsapp_baileys.py` | WhatsApp adapter via Baileys (QR pairing) |
| `channels/signal_adapter.py` | Signal adapter |
