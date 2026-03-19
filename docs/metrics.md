# Metrics

NeuralClaw exposes Prometheus-style metrics at `GET /metrics` when the dashboard HTTP server is running.

Core metrics:

- `neuralclaw_requests_total`: total completed requests.
- `neuralclaw_request_duration_ms_bucket`: request latency histogram buckets.
- `neuralclaw_threat_blocks_total{reason=...}`: blocked requests by reason.
- `neuralclaw_tool_calls_total{tool=...}`: tool invocation counts.
- `neuralclaw_circuit_state{provider=...}`: `0=closed`, `1=open`, `2=half_open`.
- `neuralclaw_memory_episodes_total`: episodic memory row count.
- `neuralclaw_process_memory_rss_bytes`: process RSS.

Suggested checks:

- Alert when any circuit is non-zero for more than 30s.
- Alert when p95 latency exceeds 5s for 5m.
- Alert when RSS exceeds the deployment profile budget.
- Alert when threat blocks spike suddenly relative to the previous hour.
