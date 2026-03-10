# 🧠 Memory System

NeuralClaw implements a **biologically-inspired memory architecture** with three
memory stores and an automatic metabolism cycle. Memories aren't just appended —
they consolidate, strengthen, decay, and get pruned over time.

---

## Three Memory Stores

### Episodic Memory

**What:** Stores specific events and conversations, like personal experiences.

**Storage:** SQLite database with FTS5 (full-text search).

**Location:** `~/.neuralclaw/data/memory.db`

```python
from neuralclaw.cortex.memory.episodic import EpisodicMemory

episodic = EpisodicMemory("~/.neuralclaw/data/memory.db")
await episodic.initialize()

# Store an episode
await episodic.store(
    content="User asked about Python decorators",
    source="conversation",
    author="User",
    importance=0.6,
)

# Search episodes
results = await episodic.search("decorators", limit=5)
```

### Semantic Memory

**What:** Stores facts and entity relationships — the knowledge graph.

**Use case:** "Paris is the capital of France" or "User prefers dark mode."

```python
from neuralclaw.cortex.memory.semantic import SemanticMemory

semantic = SemanticMemory("~/.neuralclaw/data/memory.db")
await semantic.initialize()

# Store a fact
await semantic.store(
    entity="Python",
    relation="has_feature",
    value="decorators",
    confidence=0.9,
)

# Query facts
facts = await semantic.query("Python")
```

### Procedural Memory

**What:** Reusable workflow templates matched by trigger patterns.

**Use case:** "When the user asks to deploy, run these 5 steps."

```python
from neuralclaw.cortex.memory.procedural import ProceduralMemory

procedural = ProceduralMemory("~/.neuralclaw/data/memory.db")
await procedural.initialize()

# Store a procedure
await procedural.store(
    name="deploy_app",
    trigger_patterns=["deploy", "push to production", "ship it"],
    steps=["Run tests", "Build docker image", "Push to registry", "Deploy"],
    source="synthesizer",
)

# Find matching procedures
matches = await procedural.find_matching("Can you deploy the app?")
```

---

## Memory Retrieval

The `MemoryRetriever` provides a unified search across all memory stores:

```python
from neuralclaw.cortex.memory.retrieval import MemoryRetriever

retriever = MemoryRetriever(
    episodic, semantic, bus,
    max_episodes=10,
    max_facts=5,
)

# Search across all stores
context = await retriever.retrieve("Tell me about Python decorators")
# Returns a MemoryContext with episodes + facts
```

---

## Memory Metabolism

Memories have a biological lifecycle — they aren't just appended forever.

```
Formation → Consolidation → Strengthening/Decay → Retrieval → Reconsolidation
```

### Lifecycle Stages

| Stage | What Happens |
|-------|-------------|
| **Consolidation** | Repeated episodic events merge into semantic knowledge |
| **Strengthening** | Frequently accessed memories gain importance |
| **Decay** | Stale, unused memories gradually lose relevance |
| **Pruning** | Very low-importance memories are archived |

### How It Works

The metabolism runs automatically during gateway operation:

```python
from neuralclaw.cortex.memory.metabolism import MemoryMetabolism

metabolism = MemoryMetabolism(episodic, semantic, bus)

# Check if a cycle is due
if metabolism.should_run:
    await metabolism.run_cycle()
```

### Configuration

In `~/.neuralclaw/config.toml`:

```toml
[memory]
db_path = "~/.neuralclaw/data/memory.db"
max_episodic_results = 10    # Max episodes returned per search
max_semantic_results = 5     # Max facts returned per search
importance_threshold = 0.3   # Minimum importance to keep
```

---

## Where Memories Live

```
~/.neuralclaw/
└── data/
    └── memory.db    ← SQLite database (episodic + semantic + procedural)
```

All three stores share a single SQLite database, using separate tables.
FTS5 virtual tables enable fast full-text search on episodic content.
