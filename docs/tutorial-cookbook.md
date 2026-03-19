# Tutorial Cookbook

## Local dev loop

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
neuralclaw doctor
neuralclaw chat --dev
```

## Gateway with dashboard

```bash
neuralclaw gateway --watchdog
curl http://localhost:8080/health
curl http://localhost:8080/ready
curl http://localhost:8080/metrics
```

## Containerized run

```bash
docker compose up --build
```

## Swarm seed + worker

```bash
docker compose -f docker-compose.cluster.yml up --build
```

## Full cookbook

See `docs/cookbook/` for the ten single-screen walkthroughs:

- `01-first-telegram-bot.md`
- `02-discord-bot-with-memory.md`
- `03-whatsapp-business-agent.md`
- `04-personal-ai-on-pi5.md`
- `05-multi-agent-research-crew.md`
- `06-computer-use-automation.md`
- `07-google-workspace-assistant.md`
- `08-claw-club-saas-setup.md`
- `09-custom-skill-in-10-minutes.md`
- `10-production-deployment-vps.md`

Deployment-specific guides live in:

- `docs/deployment-pi5.md`
- `docs/deployment-workstation.md`
- `docs/deployment-vps.md`
- `docs/deployment-tailscale-cluster.md`
