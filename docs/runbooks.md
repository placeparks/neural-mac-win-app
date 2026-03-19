# Operational Runbooks

Each runbook follows: **Symptom → Diagnosis → Fix → Prevention**.

---

## High Memory Usage

**Symptom:** Pi or VM OOM-killed, gateway restarts,
`neuralclaw_process_memory_rss_bytes` alert fires.

**Diagnose:**

```bash
curl http://localhost:8080/metrics | grep rss
sqlite3 ~/.neuralclaw/data/memory.db "SELECT COUNT(*) FROM episodes;"
sqlite3 ~/.neuralclaw/data/memory.db \
  "SELECT page_count * page_size / 1024 / 1024 AS mb FROM pragma_page_count(), pragma_page_size();"
sqlite3 ~/.neuralclaw/data/traces.db "SELECT COUNT(*) FROM traces;"
```

**Fix:**

```bash
neuralclaw memory prune --keep-days 30
neuralclaw traces prune --keep-days 14
sqlite3 ~/.neuralclaw/data/memory.db "VACUUM;"
sqlite3 ~/.neuralclaw/data/traces.db "VACUUM;"
```

Reduce retention in config if needed:

```toml
[memory]
max_episodic_results = 5

[traceline]
retention_days = 14
```

**Prevention:** Enable Prometheus metrics + Grafana `HighMemoryUsage` alert.

---

## Provider Outage Response

**Symptom:** Bot goes silent, circuit breaker OPEN alert fires.

**Diagnose:**

```bash
neuralclaw doctor
curl http://localhost:8080/health | jq '.probes'
neuralclaw traces list --since 1h | head -5
```

**Fix:**

```bash
# Switch primary to fallback while provider recovers
# Edit config.toml:
# [providers]
# primary = "openrouter"

neuralclaw service restart

# Reset circuit breaker manually (if provider is back)
neuralclaw provider reset-circuit --name anthropic

neuralclaw status
```

**Prevention:** Configure `fallback = ["openrouter", "local"]` so outages
are handled automatically.

---

## Security Incident Response

**Symptom:** `canary_leak` alert, high threat score burst, unusual tool call
pattern.

**Diagnose:**

```bash
neuralclaw audit list --denied --since 1h
neuralclaw traces list --since 1h | jq '.[] | select(.tags | contains(["canary_leak"]))'
neuralclaw audit show <request_id>
```

**Fix:**

```bash
# Block a specific user — add to config.toml [channels.telegram]:
# blocked_user_ids = ["12345678"]
neuralclaw service restart

# Export audit log for investigation
neuralclaw audit export --format cef --output incident_$(date +%Y%m%d).cef

# Rotate canary token (gateway restart generates new one automatically)
neuralclaw service restart
```

**Prevention:** Enable `security_block_cooldown = 300` and Prometheus
`ThreatBlocks` alert.

---

## Database Corruption Recovery

**Symptom:** `sqlite3.DatabaseError: database disk image is malformed`.

**Diagnose:**

```bash
sqlite3 ~/.neuralclaw/data/memory.db "PRAGMA integrity_check;"
```

**Fix:**

```bash
neuralclaw service stop

# Attempt SQLite recovery
sqlite3 ~/.neuralclaw/data/memory.db ".recover" \
  | sqlite3 ~/.neuralclaw/data/memory_recovered.db

# Verify recovered DB
sqlite3 ~/.neuralclaw/data/memory_recovered.db "PRAGMA integrity_check;"

# Swap if clean
mv ~/.neuralclaw/data/memory.db ~/.neuralclaw/data/memory.db.corrupt
mv ~/.neuralclaw/data/memory_recovered.db ~/.neuralclaw/data/memory.db

neuralclaw service start
```

**Automatic recovery:**

```bash
neuralclaw repair
neuralclaw doctor
```

**Prevention:** WAL mode enabled by default via `DBPool`. Regular backups:

```bash
# Add to crontab: daily backup
0 3 * * * sqlite3 ~/.neuralclaw/data/memory.db \
  ".backup /backup/memory_$(date +\%Y\%m\%d).db"
```
