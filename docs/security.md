# Security Model

NeuralClaw uses layered controls instead of a single guardrail.

## Defense Layers

1. inbound route trust evaluation
2. pre-LLM threat screening
3. intake sanitization and bounds
4. runtime policy and capability checks
5. sandboxing / environment restrictions
6. output-side Prompt Armor filtering
7. audit replay and traceline observability

## Threat Screening

`threat_screen.py` scores inbound signals for jailbreaks, prompt injection,
social engineering, obfuscated instructions, and canary-related indicators.

Important config:

```toml
[security]
threat_threshold = 0.7
block_threshold = 0.9
threat_verifier_model = ""
max_content_chars = 8000
```

## Prompt Armor v2

`output_filter.py` screens model responses before delivery when enabled.

Current checks include:

- system prompt and canary leakage
- PII not present in user input
- hallucinated tool-call payloads
- jailbreak-confirming replies
- excessive refusals on otherwise safe prompts

Relevant config:

```toml
[security]
output_filtering = true
output_pii_detection = true
output_prompt_leak_check = true
canary_tokens = true
pii_patterns = []
```

## Policy and SSRF

`policy.py` and `network.py` enforce:

- tool allowlists
- mutating-tool handling
- wall-clock and tool-call budgets
- filesystem root restrictions
- private-network and DNS-rebinding-safe URL validation

The Google Workspace and Microsoft 365 integrations also pass outbound API URLs
through SSRF validation before sending requests.

## Capabilities

High-risk capability groups now include:

- browser control / browser JS
- desktop control
- audio output / voice channel
- Google Workspace access
- Microsoft 365 access

## Audit Replay

`audit.py` persists request-scoped action records and supports:

- indexed search
- per-request replay
- export as `jsonl`, `csv`, or `cef`
- retention pruning

CLI:

```bash
neuralclaw audit list
neuralclaw audit show <request_id>
neuralclaw audit export --format jsonl
neuralclaw audit stats
```

## Traceline

`traceline.py` subscribes to the neural bus and persists request traces with:

- input/output previews
- reasoning path
- tool call previews
- request/user/channel metadata

## Idempotency

Mutating tools are protected by `IdempotencyStore` so retries do not duplicate
writes, messages, or event creation where the reasoner path retries.
