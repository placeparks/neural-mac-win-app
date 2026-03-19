# Tutorial 08 - Claw Club SaaS Setup

## Goal
Run the operator-facing SaaS profile with stronger policy defaults.

## Config
```toml
[features]
dashboard = true
swarm = true
traceline = true

[policy]
user_requests_per_minute = 15
user_requests_per_hour = 150
max_concurrent_requests = 20
```

## Run
```bash
docker compose up --build
```

## Expected result
Metrics, health, and the dashboard are all available from the container stack.
