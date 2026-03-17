# Federation

NeuralClaw supports both its native federation protocol and an additive
A2A-compatible surface.

## Native Federation Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/federation/discover` | `POST` | exchange node cards |
| `/federation/message` | `POST` | relay a task/message |
| `/federation/heartbeat` | `POST` | health / keepalive |
| `/federation/status` | `GET` | inspect known peers |

## A2A Endpoints

When both `features.a2a_federation` and `federation.a2a_enabled` are true:

| Endpoint | Method | Purpose |
|---|---|---|
| `/.well-known/agent.json` | `GET` | serve the agent card |
| `/a2a` | `POST` | JSON-RPC A2A endpoint |
| `/a2a/tasks/{task_id}` | `GET` | fetch stored task state |

Supported JSON-RPC methods:

- `message/send`
- `message/stream`
- `tasks/get`
- `tasks/cancel`
- `agent/authenticatedExtendedCard`

## Agent Card

The A2A card includes:

- node name
- persona-derived description
- bind host / port URL
- version
- capability flags
- skill metadata derived from `SkillRegistry`

## Config

```toml
[federation]
enabled = true
bind_host = "127.0.0.1"
port = 8100
seed_nodes = []
heartbeat_interval = 60
node_name = ""
a2a_enabled = false
a2a_auth_required = true
```

Bearer token auth for A2A uses the keychain secret `a2a_token`.

## Gateway Integration

The gateway:

- starts federation when swarm and federation are enabled
- joins seed nodes automatically
- starts the heartbeat loop
- connects federation peers to the mesh through `FederationBridge`
- passes persona and skill metadata into the A2A card path

## Trust and TTL

- native federation relay enforces a minimum trust score
- messages carry TTL to avoid loops
- low-trust or expired messages are rejected

## CLI

```bash
neuralclaw federation
neuralclaw federation --port 9000
```
