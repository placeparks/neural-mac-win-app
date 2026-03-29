"""
Built-in Skill: Knowledge Base — Ingest, search, and manage documents.

Provides RAG (Retrieval-Augmented Generation) capabilities by ingesting
documents into a chunked, embedded knowledge store that is automatically
queried during reasoning.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# Module-level KB reference (set by gateway on init)
_kb: Any | None = None


def set_knowledge_base(kb: Any) -> None:
    """Set the KnowledgeBase instance for this skill."""
    global _kb
    _kb = kb


async def kb_ingest(file_path: str, **kwargs: Any) -> dict[str, Any]:
    """Ingest a document file into the knowledge base."""
    if not _kb:
        return {"error": "Knowledge base is not enabled"}
    try:
        return await _kb.ingest(file_path)
    except Exception as e:
        return {"error": str(e)}


async def kb_ingest_text(text: str, title: str = "", source: str = "", **kwargs: Any) -> dict[str, Any]:
    """Ingest raw text into the knowledge base."""
    if not _kb:
        return {"error": "Knowledge base is not enabled"}
    try:
        return await _kb.ingest_text(text, source=source, title=title)
    except Exception as e:
        return {"error": str(e)}


async def kb_search(query: str, top_k: int = 5, **kwargs: Any) -> dict[str, Any]:
    """Search the knowledge base for relevant content."""
    if not _kb:
        return {"error": "Knowledge base is not enabled"}
    try:
        results = await _kb.search(query, top_k=top_k)
        return {
            "results": [
                {
                    "content": r.chunk.content[:500],
                    "score": round(r.score, 4),
                    "doc_id": r.chunk.doc_id,
                    "chunk_index": r.chunk.chunk_index,
                    "filename": r.document.filename if r.document else "",
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as e:
        return {"error": str(e)}


async def kb_list(**kwargs: Any) -> dict[str, Any]:
    """List all documents in the knowledge base."""
    if not _kb:
        return {"error": "Knowledge base is not enabled"}
    try:
        docs = await _kb.list_documents()
        return {
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "source": d.source,
                    "doc_type": d.doc_type,
                    "chunk_count": d.chunk_count,
                }
                for d in docs
            ],
            "count": len(docs),
        }
    except Exception as e:
        return {"error": str(e)}


async def kb_delete(doc_id: str, **kwargs: Any) -> dict[str, Any]:
    """Delete a document from the knowledge base."""
    if not _kb:
        return {"error": "Knowledge base is not enabled"}
    try:
        deleted = await _kb.delete_document(doc_id)
        if deleted:
            return {"success": True, "doc_id": doc_id}
        return {"error": f"Document not found: {doc_id}"}
    except Exception as e:
        return {"error": str(e)}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="knowledge_base",
        description="Ingest, search, and manage documents in the RAG knowledge base",
        capabilities=[Capability.FILESYSTEM_READ],
        tools=[
            ToolDefinition(
                name="kb_ingest",
                description="Ingest a document file (txt, md, html, csv, pdf, json) into the knowledge base",
                parameters=[
                    ToolParameter(
                        name="file_path", type="string",
                        description="Path to the document file to ingest",
                    ),
                ],
                handler=kb_ingest,
            ),
            ToolDefinition(
                name="kb_ingest_text",
                description="Ingest raw text content into the knowledge base",
                parameters=[
                    ToolParameter(name="text", type="string", description="Text content to ingest"),
                    ToolParameter(
                        name="title", type="string",
                        description="Optional title for the document",
                        required=False, default="",
                    ),
                    ToolParameter(
                        name="source", type="string",
                        description="Optional source identifier",
                        required=False, default="",
                    ),
                ],
                handler=kb_ingest_text,
            ),
            ToolDefinition(
                name="kb_search",
                description="Semantic search across all knowledge base documents",
                parameters=[
                    ToolParameter(name="query", type="string", description="Search query"),
                    ToolParameter(
                        name="top_k", type="integer",
                        description="Maximum number of results to return",
                        required=False, default=5,
                    ),
                ],
                handler=kb_search,
            ),
            ToolDefinition(
                name="kb_list",
                description="List all documents in the knowledge base",
                parameters=[],
                handler=kb_list,
            ),
            ToolDefinition(
                name="kb_delete",
                description="Delete a document and all its chunks from the knowledge base",
                parameters=[
                    ToolParameter(name="doc_id", type="string", description="Document ID to delete"),
                ],
                handler=kb_delete,
            ),
        ],
    )
