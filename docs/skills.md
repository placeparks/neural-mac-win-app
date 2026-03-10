# 🔧 Skills Framework

NeuralClaw includes a **skill framework** with built-in tools, a cryptographic
marketplace for sharing skills, and a credits-based economy.

---

## Built-in Skills

| Skill | File | Tools Provided |
|-------|------|---------------|
| **Web Search** | `skills/builtins/web_search.py` | Search the web |
| **File Operations** | `skills/builtins/file_ops.py` | Read, write, list files |
| **Code Execution** | `skills/builtins/code_exec.py` | Run code in sandbox |
| **Calendar** | `skills/builtins/calendar_skill.py` | Date/time operations |

Built-in skills are loaded automatically when the gateway starts:

```python
from neuralclaw.skills.registry import SkillRegistry

registry = SkillRegistry()
registry.load_builtins()

print(f"Skills loaded: {registry.count}")
print(f"Tools available: {registry.tool_count}")
```

---

## Skill Manifest

Every skill declares its capabilities via a manifest:

```python
from neuralclaw.skills.manifest import SkillManifest

manifest = SkillManifest(
    name="my_skill",
    version="1.0.0",
    description="Does something useful",
    author="nick",
    capabilities=["network", "file_read"],  # Required permissions
    tools=[...],  # Tool definitions
)
```

---

## Skill Marketplace

The marketplace enables **signed skill distribution** with static analysis.

### Publishing a Skill

```python
from neuralclaw.skills.marketplace import SkillMarketplace

mp = SkillMarketplace()

# Publish with Ed25519 signing + static analysis
package, findings = mp.publish(
    name="web_scraper",
    version="1.0",
    author="nick",
    description="Scrapes web pages for data extraction",
    code=skill_source_code,
    private_key=my_ed25519_private_key,
)

# Check security findings
for finding in findings:
    print(f"  {finding.severity}: {finding.description}")

print(f"Risk score: {package.risk_score}")  # 0.0 (safe) → 1.0 (dangerous)
```

### Static Analysis

Before a skill is published, it's scanned for:

| Check | What It Detects |
|-------|----------------|
| Shell execution | `os.system()`, `subprocess.run()`, etc. |
| Network exfiltration | Unauthorized HTTP requests |
| Path traversal | Attempts to access files outside sandbox |
| Obfuscation | Base64 encoding, `exec()`, `eval()` usage |

### Installing a Skill

```python
mp.install("web_scraper")
```

---

## Skill Economy

A credits-based economy with usage tracking, ratings, and leaderboards.

### Setup

```python
from neuralclaw.skills.economy import SkillEconomy

econ = SkillEconomy()

# Register an author
econ.register_author("nick", "Nick")

# Register a skill
econ.register_skill("web_scraper", "nick")
```

### Usage Tracking

```python
# Record skill usage
econ.record_usage("web_scraper", user_id="user1", success=True)
econ.record_usage("web_scraper", user_id="user2", success=True)
econ.record_usage("web_scraper", user_id="user3", success=False)
```

### Ratings & Reviews

```python
econ.rate_skill(
    "web_scraper",
    rater_id="user1",
    score=4.5,
    review="Excellent scraper, very fast!",
)
```

### Leaderboards

```python
# Trending skills
trending = econ.get_trending()
for skill in trending:
    print(f"  {skill['name']}: {skill['usage_count']} uses")

# Top authors
authors = econ.get_author_leaderboard()
for a in authors:
    print(f"  {a['name']}: {a['total_credits']} credits")
```

---

## Creating Custom Skills

A skill is a Python function that follows this pattern:

```python
async def my_tool(query: str) -> str:
    """Search for something useful.

    Args:
        query: What to search for
    """
    # Your logic here
    return f"Result for: {query}"
```

Register it in the skill registry to make it available to the reasoning
pipeline:

```python
registry.register_tool(
    name="my_search",
    description="Searches for useful things",
    function=my_tool,
    parameters={
        "query": {"type": "string", "description": "Search query"},
    },
)
```

---

## Security

Skills run inside the [Action Cortex](security.md) with:
- **Capability-based permissions** — Skills must declare what they need
- **Sandboxed execution** — Code runs in a restricted subprocess
- **Timeout limits** — Default 30 seconds (configurable)
- **Audit logging** — Every action is logged
