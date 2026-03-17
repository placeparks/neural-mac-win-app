# Memory System

NeuralClaw now has five cooperating memory layers:

- episodic memory
- semantic memory
- procedural memory
- vector memory
- user identity memory

## Episodic Memory

Stores concrete interactions in SQLite with FTS5 search.

## Semantic Memory

Stores facts and entity relationships extracted from interactions and
distillation.

## Procedural Memory

Stores reusable workflow templates keyed by trigger patterns.

## Vector Memory

`vector.py` adds similarity-based retrieval alongside lexical search.

Important config:

- `memory.vector_memory`
- `memory.embedding_provider`
- `memory.embedding_model`
- `memory.embedding_dimension`
- `memory.vector_similarity_top_k`

Integration points:

- episodic writes are embedded and indexed
- retriever merges vector hits with lexical and semantic results
- metabolism deletes vector rows when episodes are pruned

## Identity Memory

`identity.py` persists a canonical user model across channels.

It tracks:

- platform aliases
- communication style
- active projects
- expertise domains
- language and timezone
- explicit user preferences
- session and message counts

When enabled, the gateway injects a user-context prompt section into
deliberative and reflective reasoning.

## Retrieval

`MemoryRetriever` merges:

- recent episodic context
- lexical episode search
- semantic facts
- vector similarity results

## Metabolism

`MemoryMetabolism` still handles consolidation and pruning, and now also keeps
vector state coherent with episodic retention.
