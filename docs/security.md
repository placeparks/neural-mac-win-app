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

## SkillForge Security

SkillForge-generated skills pass through the same layered security model as the rest of NeuralClaw, with additional checks specific to code generation:

- **SSRF validation** -- All URLs used by generated skills pass through `validate_url_with_dns()`, blocking private-network and DNS-rebinding attacks.
- **Static analysis** -- Generated code is scanned before registration. High-severity findings are blocked automatically, including keyring access, raw socket usage, and OS-level system calls (`os.system`, `subprocess` with shell=True, etc.).
- **Mandatory sandbox testing** -- Every generated skill must pass a sandbox test run before it is registered with the gateway. Skills that fail sandbox testing are not loaded.
- **Filesystem access disabled by default** -- `allow_filesystem_skills = false` is the default, preventing generated skills from reading or writing the local filesystem.
- **API key handling** -- Generated skills reference API keys via `os.getenv()`. Credentials are never hardcoded into skill source files.
- **Operator-owned skills** -- Skills stored in `~/.neuralclaw/skills/` are operator-owned and locally managed. They are not part of any shared marketplace and do not execute without the operator's gateway loading them.

## SkillScout Security

SkillScout searches public skill registries to find candidates that match a natural-language query, then optionally hands the best match to SkillForge for code generation.

- **Read-only searches** -- Scout performs only HTTP GET requests against public registries. No data is written or modified on the remote side.
- **No credentials sent** -- Registry searches never transmit API keys, tokens, or any other credentials. Only the search query string is sent.
- **Full SkillForge pipeline for forging** -- When Scout triggers SkillForge to generate a skill from a candidate, the entire SkillForge security pipeline applies: static analysis, mandatory sandbox testing, SSRF validation, and all other checks described in the SkillForge Security section above.

## Idempotency

Mutating tools are protected by `IdempotencyStore` so retries do not duplicate
writes, messages, or event creation where the reasoner path retries.
