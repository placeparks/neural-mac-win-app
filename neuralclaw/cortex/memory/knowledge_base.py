"""
Knowledge Base — RAG document ingestion and retrieval.

Ingests documents (text, markdown, HTML, CSV, PDF) into chunked, embedded,
searchable knowledge. The search results are injected into the reasoning
pipeline through MemoryRetriever for automatic context augmentation.

Storage is SQLite-backed with embeddings delegated to VectorMemory's
embedding pipeline (local deterministic or remote provider).
"""

from __future__ import annotations

import csv
import hashlib
import html.parser
import io
import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite

from neuralclaw.bus.neural_bus import EventType, NeuralBus

log = logging.getLogger("neuralclaw.memory.knowledge_base")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class KBDocument:
    """Ingested document metadata."""
    id: str
    filename: str
    source: str
    doc_type: str
    ingested_at: float
    chunk_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KBChunk:
    """A single chunk of a document with its embedding."""
    id: str
    doc_id: str
    chunk_index: int
    content: str
    created_at: float


@dataclass
class KBSearchResult:
    """Search result containing a chunk and its similarity score."""
    chunk: KBChunk
    score: float
    document: KBDocument | None = None


# ---------------------------------------------------------------------------
# HTML stripper (stdlib only)
# ---------------------------------------------------------------------------

class _HTMLStripper(html.parser.HTMLParser):
    """Simple HTML tag stripper using stdlib."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(raw: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(raw)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    SQLite-backed knowledge base with chunked document storage and
    cosine-similarity search via delegated embeddings.
    """

    def __init__(
        self,
        db_path: str,
        vector_memory: Any | None = None,
        bus: NeuralBus | None = None,
        chunk_size: int = 1024,
        overlap: int = 128,
        retrieval_top_k: int = 5,
        max_doc_size_mb: int = 50,
    ) -> None:
        self._db_path = db_path
        self._vector_memory = vector_memory
        self._bus = bus
        self._chunk_size = max(64, chunk_size)
        self._overlap = max(0, min(overlap, chunk_size // 2))
        self._retrieval_top_k = retrieval_top_k
        self._max_doc_bytes = max_doc_size_mb * 1024 * 1024
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create database tables."""
        try:
            self._db = await aiosqlite.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            await self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    doc_type TEXT NOT NULL DEFAULT 'text',
                    ingested_at REAL NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS kb_chunks (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_id
                    ON kb_chunks(doc_id);
                """
            )
            await self._db.commit()
        except Exception as exc:
            log.error("KnowledgeBase initialize failed: %s", exc)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def ping(self) -> bool:
        """Readiness check."""
        if not self._db:
            return False
        try:
            rows = await self._db.execute_fetchall("SELECT 1")
            return bool(rows and rows[0][0] == 1)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    async def ingest(self, file_path: str, source: str = "") -> dict[str, Any]:
        """Ingest a document file into the knowledge base."""
        if not self._db:
            return {"error": "Knowledge base not initialized"}

        p = Path(file_path)
        if not p.exists():
            return {"error": f"File not found: {file_path}"}
        if not p.is_file():
            return {"error": f"Not a file: {file_path}"}
        if p.stat().st_size > self._max_doc_bytes:
            return {"error": f"File exceeds {self._max_doc_bytes // (1024*1024)}MB limit"}

        ext = p.suffix.lower()
        doc_type = self._detect_type(ext)

        try:
            text = self._parse_file(p, doc_type)
        except Exception as exc:
            return {"error": f"Failed to parse file: {exc}"}

        if not text.strip():
            return {"error": "File is empty or could not be parsed"}

        return await self._ingest_text_internal(
            text=text,
            filename=p.name,
            source=source or str(p),
            doc_type=doc_type,
            metadata={"path": str(p), "size_bytes": p.stat().st_size},
        )

    async def ingest_text(
        self,
        text: str,
        source: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        """Ingest raw text into the knowledge base."""
        if not self._db:
            return {"error": "Knowledge base not initialized"}
        if not text.strip():
            return {"error": "Text is empty"}

        return await self._ingest_text_internal(
            text=text,
            filename=title or f"text_{uuid.uuid4().hex[:8]}",
            source=source,
            doc_type="text",
            metadata={"char_count": len(text)},
        )

    async def _ingest_text_internal(
        self,
        text: str,
        filename: str,
        source: str,
        doc_type: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Core ingestion: chunk, embed, store."""
        doc_id = uuid.uuid4().hex[:12]
        chunks = self._chunk_text(text)

        # Insert document first (FK constraint: chunks reference doc)
        await self._db.execute(
            """
            INSERT INTO kb_documents (id, filename, source, doc_type, ingested_at, chunk_count, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, filename, source, doc_type, time.time(), len(chunks), json.dumps(metadata)),
        )

        for i, chunk_text in enumerate(chunks):
            chunk_id = uuid.uuid4().hex[:12]
            embedding = await self._generate_embedding(chunk_text)
            await self._db.execute(
                """
                INSERT INTO kb_chunks (id, doc_id, chunk_index, content, embedding_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, doc_id, i, chunk_text, json.dumps(embedding), time.time()),
            )

        await self._db.commit()

        if self._bus:
            await self._bus.publish(
                EventType.RAG_INGESTED,
                {
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_count": len(chunks),
                    "doc_type": doc_type,
                },
                source="memory.knowledge_base",
            )

        return {
            "success": True,
            "doc_id": doc_id,
            "filename": filename,
            "chunk_count": len(chunks),
            "doc_type": doc_type,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(self, query: str, top_k: int = 0) -> list[KBSearchResult]:
        """Semantic search across all KB chunks."""
        if not self._db:
            return []

        top_k = top_k or self._retrieval_top_k
        query_embedding = await self._generate_embedding(query)

        rows = await self._db.execute_fetchall(
            "SELECT id, doc_id, chunk_index, content, embedding_json, created_at FROM kb_chunks"
        )

        results: list[KBSearchResult] = []
        for row in rows:
            chunk_id, doc_id, chunk_index, content, emb_json, created_at = row
            stored_embedding = json.loads(emb_json)
            if not stored_embedding:
                continue
            score = self._cosine_similarity(query_embedding, stored_embedding)
            if score > 0:
                results.append(KBSearchResult(
                    chunk=KBChunk(
                        id=chunk_id,
                        doc_id=doc_id,
                        chunk_index=chunk_index,
                        content=content,
                        created_at=created_at,
                    ),
                    score=score,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]

        # Attach document metadata to results
        for r in results:
            r.document = await self._get_document(r.chunk.doc_id)

        if self._bus:
            await self._bus.publish(
                EventType.RAG_SEARCHED,
                {
                    "query": query[:100],
                    "result_count": len(results),
                },
                source="memory.knowledge_base",
            )

        return results

    # ------------------------------------------------------------------
    # Document management
    # ------------------------------------------------------------------

    async def list_documents(self) -> list[KBDocument]:
        """List all ingested documents."""
        if not self._db:
            return []
        rows = await self._db.execute_fetchall(
            "SELECT id, filename, source, doc_type, ingested_at, chunk_count, metadata_json "
            "FROM kb_documents ORDER BY ingested_at DESC"
        )
        return [
            KBDocument(
                id=r[0], filename=r[1], source=r[2], doc_type=r[3],
                ingested_at=r[4], chunk_count=r[5],
                metadata=json.loads(r[6]) if r[6] else {},
            )
            for r in rows
        ]

    async def delete_document(self, doc_id: str) -> bool:
        """Delete a document and all its chunks."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "DELETE FROM kb_documents WHERE id = ?", (doc_id,)
        )
        # Chunks deleted via ON DELETE CASCADE
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_document_chunks(self, doc_id: str) -> list[KBChunk]:
        """Get all chunks for a document (for MCP resource reading)."""
        if not self._db:
            return []
        rows = await self._db.execute_fetchall(
            "SELECT id, doc_id, chunk_index, content, created_at "
            "FROM kb_chunks WHERE doc_id = ? ORDER BY chunk_index",
            (doc_id,),
        )
        return [
            KBChunk(id=r[0], doc_id=r[1], chunk_index=r[2], content=r[3], created_at=r[4])
            for r in rows
        ]

    async def _get_document(self, doc_id: str) -> KBDocument | None:
        """Get a single document by ID."""
        if not self._db:
            return None
        rows = await self._db.execute_fetchall(
            "SELECT id, filename, source, doc_type, ingested_at, chunk_count, metadata_json "
            "FROM kb_documents WHERE id = ?",
            (doc_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return KBDocument(
            id=r[0], filename=r[1], source=r[2], doc_type=r[3],
            ingested_at=r[4], chunk_count=r[5],
            metadata=json.loads(r[6]) if r[6] else {},
        )

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks on paragraph boundaries."""
        if not text.strip():
            return []

        # Split on double newlines (paragraphs) first
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 <= self._chunk_size:
                current = f"{current}\n\n{para}" if current else para
            else:
                if current:
                    chunks.append(current)
                # If a single paragraph exceeds chunk_size, split by sentences
                if len(para) > self._chunk_size:
                    sub_chunks = self._split_long_text(para)
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    current = para

        if current:
            chunks.append(current)

        # Apply overlap: prepend tail of previous chunk to current
        if self._overlap > 0 and len(chunks) > 1:
            overlapped: list[str] = [chunks[0]]
            for i in range(1, len(chunks)):
                prev_tail = chunks[i - 1][-self._overlap:]
                overlapped.append(prev_tail + "\n" + chunks[i])
            chunks = overlapped

        return chunks if chunks else [text[:self._chunk_size]]

    def _split_long_text(self, text: str) -> list[str]:
        """Split a long text block into fixed-size chunks."""
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self._chunk_size
            # Try to break at a sentence boundary
            if end < len(text):
                for sep in (". ", "! ", "? ", "\n", " "):
                    last = text.rfind(sep, start + self._chunk_size // 2, end)
                    if last > start:
                        end = last + len(sep)
                        break
            chunks.append(text[start:end].strip())
            start = end
        return [c for c in chunks if c]

    # ------------------------------------------------------------------
    # Embedding (delegates to VectorMemory)
    # ------------------------------------------------------------------

    async def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding, delegating to VectorMemory if available."""
        if self._vector_memory:
            try:
                return await self._vector_memory._generate_embedding(text)
            except Exception:
                pass
        # Deterministic local fallback (same as VectorMemory)
        return self._local_embedding(text)

    def _local_embedding(self, text: str) -> list[float]:
        """Deterministic hash-based embedding fallback."""
        dimension = 768
        h = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
        vec: list[float] = []
        for i in range(dimension):
            byte_idx = i % len(h)
            vec.append((h[byte_idx] + i) / 256.0 - 0.5)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        min_len = min(len(a), len(b))
        if min_len == 0:
            return 0.0
        dot = sum(a[i] * b[i] for i in range(min_len))
        norm_a = math.sqrt(sum(x * x for x in a[:min_len])) or 1.0
        norm_b = math.sqrt(sum(x * x for x in b[:min_len])) or 1.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # File parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_type(ext: str) -> str:
        """Detect document type from file extension."""
        mapping = {
            ".txt": "text", ".md": "markdown", ".markdown": "markdown",
            ".html": "html", ".htm": "html",
            ".csv": "csv", ".tsv": "csv",
            ".pdf": "pdf",
            ".json": "json",
        }
        return mapping.get(ext, "text")

    @staticmethod
    def _parse_file(path: Path, doc_type: str) -> str:
        """Parse file content into plain text."""
        if doc_type == "pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                return "\n\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            except ImportError:
                raise RuntimeError(
                    "PDF support requires 'pypdf'. Install with: pip install pypdf"
                )

        raw = path.read_text(encoding="utf-8", errors="replace")

        if doc_type == "html":
            return _strip_html(raw)

        if doc_type == "csv":
            reader = csv.reader(io.StringIO(raw))
            rows = list(reader)
            if not rows:
                return ""
            return "\n".join(" | ".join(row) for row in rows)

        if doc_type == "json":
            try:
                data = json.loads(raw)
                return json.dumps(data, indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                return raw

        # text / markdown — return as-is
        return raw
