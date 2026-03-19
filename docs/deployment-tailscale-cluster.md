# Multi-Node Cluster via Tailscale

Orchestrator node + worker nodes connected via Tailscale mesh. Workers handle
delegated tasks; orchestrator handles channels, federation, and dashboard.

## Orchestrator Node Config

```toml
[federation]
enabled    = true
port       = 8100
bind_host  = "0.0.0.0"       # safe — Tailscale firewall
node_name  = "orchestrator"
seed_nodes = []               # orchestrator is the seed

[channels.telegram]
enabled = true                # orchestrator handles all channels
```

## Worker Node Config

```toml
[federation]
enabled    = true
port       = 8100
bind_host  = "0.0.0.0"
node_name  = "worker-1"
seed_nodes = ["100.68.182.87:8100"]  # Tailscale IP of orchestrator

[channels.telegram]
enabled = false               # workers don't listen — orchestrator delegates
```

## Tailscale ACL

Add to Tailscale admin console or `/etc/tailscale/acls.json`:

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:neuralclaw-node"],
      "dst": ["tag:neuralclaw-node:8100"]
    }
  ],
  "tagOwners": {
    "tag:neuralclaw-node": ["your@email.com"]
  }
}
```

## Docker Compose Cluster

Use `docker-compose.cluster.yml` for containerized multi-node:

```bash
docker compose -f docker-compose.cluster.yml up -d
```

## Verify

```bash
# On orchestrator
curl http://localhost:8080/swarm
curl http://localhost:8080/health

# On each worker
curl http://localhost:8080/health
```

The `/swarm` endpoint shows all connected agents and their federation status.
