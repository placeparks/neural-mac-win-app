"""
Vector memory with optional remote embeddings and deterministic local fallback.

Stores embeddings in SQLite and performs cosine-similarity search in Python so
the feature works even when sqlite-vec or external embedding providers are not
available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass

import aiohttp
import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus

log = logging.getLogger("neuralclaw.memory.vector")


@dataclass
class VectorResult:
    """Similarity search result from the vector store."""

    ref_id: str
    source: str
    score: float
    content_preview: str


@dataclass
class VectorEntry:
    """Stored vector row metadata."""

    id: str
    source: str
    ref_id: str
    content_preview: str
    created_at: float


class VectorMemory:
    """
    SQLite-backed vector memory.

    The implementation prefers configured embedding providers but falls back to
    a deterministic local embedding strategy so the store remains usable in
    tests and offline environments.
    """

    def __init__(
        self,
        db_path: str,
        embedding_provider: str = "local",
        embedding_model: str = "nomic-embed-text",
        dimension: int = 768,
        bus: NeuralBus | None = None,
        ollama_base_url: str = "",
    ) -> None:
        self._db_path = db_path
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._dimension = max(8, dimension)
        self._bus = bus
        self._db: aiosqlite.Connection | None = None
        self._ollama_base_url = ollama_base_url

    async def initialize(self) -> None:
        """Initialize the vector store schema."""
        try:
            self._db = await aiosqlite.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS vec_embeddings (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    content_preview TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL DEFAULT (unixepoch('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_vec_embeddings_ref_id
                    ON vec_embeddings(ref_id);
                CREATE INDEX IF NOT EXISTS idx_vec_embeddings_source
                    ON vec_embeddings(source);
                """
            )
            await self._db.commit()
        except Exception as exc:
            await self._publish_error("initialize", exc)

    async def embed_and_store(
        self,
        content: str,
        ref_id: str,
        source: str = "episodic",
    ) -> str:
        """Generate an embedding and store it, returning the vector row ID."""
        if not self._db:
            await self._publish_error("embed_and_store", RuntimeError("Vector memory is not initialized"))
            return ""

        try:
            embedding = await self._generate_embedding(content)
            vector_id = uuid.uuid4().hex[:12]
            await self._db.execute(
                "DELETE FROM vec_embeddings WHERE ref_id = ? AND source = ?",
                (ref_id, source),
            )
            await self._db.execute(
                """
                INSERT INTO vec_embeddings (id, source, ref_id, embedding_json, content_preview, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    vector_id,
                    source,
                    ref_id,
                    json.dumps(embedding),
                    content[:200],
                    time.time(),
                ),
            )
            await self._db.commit()
            if self._bus:
                await self._bus.publish(
                    EventType.MEMORY_STORED,
                    {
                        "component": "vector_memory",
                        "vector_id": vector_id,
                        "ref_id": ref_id,
                        "source": source,
                    },
                    source="memory.vector",
                )
            return vector_id
        except Exception as exc:
            await self._publish_error("embed_and_store", exc)
            return ""

    async def similarity_search(
        self,
        query: str,
        top_k: int = 10,
        source_filter: str | None = None,
        scan_limit: int = 5000,
    ) -> list[VectorResult]:
        """Search for similar vectors using cosine similarity.

        Args:
            scan_limit: Max rows to load for brute-force comparison.
                        Rows are selected by most-recently-inserted first.
        """
        if not self._db:
            await self._publish_error("similarity_search", RuntimeError("Vector memory is not initialized"))
            return []

        try:
            query_embedding = await self._generate_embedding(query)

            # Build query with source filter + scan cap to prevent OOM
            sql = "SELECT ref_id, source, embedding_json, content_preview FROM vec_embeddings"
            params: list[str | int] = []
            if source_filter:
                sql += " WHERE source = ?"
                params.append(source_filter)
            sql += " ORDER BY rowid DESC LIMIT ?"
            params.append(scan_limit)

            rows = await self._db.execute_fetchall(sql, tuple(params))

            results: list[VectorResult] = []
            for ref_id, source, embedding_json, preview in rows:
                stored_embedding = self._coerce_dimension(json.loads(embedding_json))
                score = self._cosine_similarity(query_embedding, stored_embedding)
                if score > 0:
                    results.append(
                        VectorResult(
                            ref_id=ref_id,
                            source=source,
                            score=score,
                            content_preview=preview,
                        )
                    )

            results.sort(key=lambda item: item.score, reverse=True)

            if self._bus:
                await self._bus.publish(
                    EventType.MEMORY_RETRIEVED,
                    {
                        "component": "vector_memory",
                        "query": query[:100],
                        "results": len(results[:top_k]),
                        "scanned": len(rows),
                        "scan_limit": scan_limit,
                        "source_filter": source_filter or "",
                    },
                    source="memory.vector",
                )

            return results[:top_k]
        except Exception as exc:
            await self._publish_error("similarity_search", exc)
            return []

    async def delete_by_ref(self, ref_id: str) -> None:
        """Delete any vectors associated with a source record."""
        if not self._db:
            await self._publish_error("delete_by_ref", RuntimeError("Vector memory is not initialized"))
            return

        try:
            await self._db.execute("DELETE FROM vec_embeddings WHERE ref_id = ?", (ref_id,))
            await self._db.commit()
        except Exception as exc:
            await self._publish_error("delete_by_ref", exc)

    async def delete(self, vector_id: str) -> None:
        """Delete a vector by row ID."""
        if not self._db:
            await self._publish_error("delete", RuntimeError("Vector memory is not initialized"))
            return

        try:
            await self._db.execute("DELETE FROM vec_embeddings WHERE id = ?", (vector_id,))
            await self._db.commit()
        except Exception as exc:
            await self._publish_error("delete", exc)

    async def list_entries(
        self,
        query: str = "",
        limit: int = 50,
        source_filter: str | None = None,
    ) -> list[VectorEntry]:
        """List stored vector rows for inspection."""
        if not self._db:
            await self._publish_error("list_entries", RuntimeError("Vector memory is not initialized"))
            return []

        try:
            sql = (
                "SELECT id, source, ref_id, content_preview, created_at "
                "FROM vec_embeddings WHERE 1 = 1"
            )
            params: list[object] = []
            if source_filter:
                sql += " AND source = ?"
                params.append(source_filter)
            if query.strip():
                sql += " AND (content_preview LIKE ? OR ref_id LIKE ?)"
                like = f"%{query.strip()}%"
                params.extend([like, like])
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = await self._db.execute_fetchall(sql, tuple(params))
            return [
                VectorEntry(
                    id=row[0],
                    source=row[1],
                    ref_id=row[2],
                    content_preview=row[3] or "",
                    created_at=float(row[4] or 0.0),
                )
                for row in rows
            ]
        except Exception as exc:
            await self._publish_error("list_entries", exc)
            return []

    async def count(self) -> int:
        """Return the total number of stored embeddings."""
        if not self._db:
            return 0
        rows = await self._db.execute_fetchall("SELECT COUNT(*) FROM vec_embeddings")
        return int(rows[0][0]) if rows else 0

    async def clear(self) -> int:
        """Delete all embeddings and return deleted count."""
        if not self._db:
            await self._publish_error("clear", RuntimeError("Vector memory is not initialized"))
            return 0

        try:
            rows = await self._db.execute_fetchall("SELECT COUNT(*) FROM vec_embeddings")
            count = int(rows[0][0]) if rows else 0
            await self._db.execute("DELETE FROM vec_embeddings")
            await self._db.commit()
            return count
        except Exception as exc:
            await self._publish_error("clear", exc)
            return 0

    async def prune(self, keep_days: int = 90) -> int:
        """Delete stale embeddings older than the retention window."""
        if not self._db:
            await self._publish_error("prune", RuntimeError("Vector memory is not initialized"))
            return 0

        try:
            cutoff = time.time() - (keep_days * 86400)
            rows = await self._db.execute_fetchall(
                "SELECT COUNT(*) FROM vec_embeddings WHERE created_at < ?",
                (cutoff,),
            )
            count = int(rows[0][0]) if rows else 0
            await self._db.execute(
                "DELETE FROM vec_embeddings WHERE created_at < ?",
                (cutoff,),
            )
            await self._db.commit()
            return count
        except Exception as exc:
            await self._publish_error("prune", exc)
            return 0

    async def close(self) -> None:
        """Close the vector store connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def ping(self) -> bool:
        """Cheap readiness check."""
        if not self._db:
            return False
        rows = await self._db.execute_fetchall("SELECT 1")
        return bool(rows and rows[0][0] == 1)

    async def _generate_embedding(self, text: str) -> list[float]:
        provider = (self._embedding_provider or "local").strip().lower()
        text = text or ""

        if provider == "openai":
            embedding = await self._embed_openai(text)
            if embedding:
                return self._coerce_dimension(embedding)

        if provider == "local":
            # If no model is configured or the configured model fails,
            # auto-detect an embedding-capable model from the Ollama server.
            if not self._embedding_model:
                self._embedding_model = await self._discover_embed_model()

            embedding = await self._embed_ollama(text)
            if embedding:
                return self._coerce_dimension(embedding)

            # First attempt failed — model may not be loaded. Try auto-detection
            # once to recover (e.g., config pointed at a deleted model).
            discovered = await self._discover_embed_model()
            if discovered and discovered != self._embedding_model:
                log.info(
                    "Embed model '%s' failed — retrying with discovered model '%s'",
                    self._embedding_model,
                    discovered,
                )
                self._embedding_model = discovered
                embedding = await self._embed_ollama(text)
                if embedding:
                    return self._coerce_dimension(embedding)

        return self._deterministic_embedding(text)

    async def _embed_openai(self, text: str) -> list[float] | None:
        try:
            from neuralclaw.config import get_api_key

            api_key = get_api_key("openai")
            if not api_key:
                return None

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": self._embedding_model, "input": text},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status >= 400:
                        return None
                    payload = await resp.json()
            data = payload.get("data", [])
            if not data:
                return None
            embedding = data[0].get("embedding")
            if isinstance(embedding, list):
                return [float(v) for v in embedding]
        except Exception:
            return None
        return None

    async def _discover_embed_model(self) -> str:
        """Query Ollama and return the best available embedding model name.

        Preference order:
        1. Models with "embed" in the name (purpose-built)
        2. Models with "nomic" in the name (common embedding models)
        3. First available model as a last resort
        Returns empty string if the server is unreachable.
        """
        base_url = (
            self._ollama_base_url
            or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status >= 400:
                        return ""
                    payload = await resp.json()
            models: list[dict] = payload.get("models", [])
            if not models:
                return ""
            names = [m.get("name", "") for m in models if m.get("name")]
            # Priority 1: dedicated embed model
            embed_names = [n for n in names if "embed" in n.lower()]
            if embed_names:
                return embed_names[0]
            # Priority 2: nomic (popular embedding model family)
            nomic_names = [n for n in names if "nomic" in n.lower()]
            if nomic_names:
                return nomic_names[0]
            # Fallback: first available
            return names[0]
        except Exception:
            return ""

    async def _embed_ollama(self, text: str) -> list[float] | None:
        base_url = (
            self._ollama_base_url
            or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")
        # Strip /v1 suffix if present — Ollama native API doesn't use it
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base_url}/api/embed",
                    json={"model": self._embedding_model, "input": text},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status < 400:
                        payload = await resp.json()
                        embeddings = payload.get("embeddings")
                        if isinstance(embeddings, list) and embeddings:
                            first = embeddings[0]
                            if isinstance(first, list):
                                return [float(v) for v in first]
        except Exception:
            pass

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{base_url}/api/embeddings",
                    json={"model": self._embedding_model, "prompt": text},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status >= 400:
                        return None
                    payload = await resp.json()
            embedding = payload.get("embedding")
            if isinstance(embedding, list):
                return [float(v) for v in embedding]
        except Exception:
            return None
        return None

    def _deterministic_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = self._tokenize(text)

        if not tokens:
            return vector

        for token in tokens:
            index = self._stable_index(token)
            vector[index] += 1.0

            if len(token) >= 3:
                for i in range(len(token) - 2):
                    trigram = token[i : i + 3]
                    vector[self._stable_index(f"tri:{trigram}")] += 0.25

        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _stable_index(self, token: str) -> int:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big") % self._dimension

    def _coerce_dimension(self, embedding: list[float]) -> list[float]:
        original_len = len(embedding)
        coerced = [float(v) for v in embedding[: self._dimension]]
        if len(coerced) < self._dimension:
            log.warning(
                "Embedding dimension mismatch: got %d, expected %d — padding with zeros. "
                "Check embedding_model and embedding_dimension in config.",
                original_len, self._dimension,
            )
            coerced.extend([0.0] * (self._dimension - len(coerced)))

        magnitude = math.sqrt(sum(value * value for value in coerced))
        if magnitude == 0:
            return coerced
        return [value / magnitude for value in coerced]

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=False))

    async def _publish_error(self, operation: str, exc: Exception) -> None:
        if self._bus:
            await self._bus.publish(
                EventType.ERROR,
                {
                    "component": "vector_memory",
                    "operation": operation,
                    "error": str(exc),
                },
                source="memory.vector",
            )
