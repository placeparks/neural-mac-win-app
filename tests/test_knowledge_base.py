"""Tests for the RAG Knowledge Base module."""

import asyncio

import pytest

from neuralclaw.cortex.memory.knowledge_base import KnowledgeBase, KBDocument, KBSearchResult


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_kb.db")


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestKnowledgeBaseLifecycle:
    def test_init_and_ping(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            assert await kb.ping()
            await kb.close()
            assert not await kb.ping()
        _run(go())


class TestIngestion:
    def test_ingest_text(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            result = await kb.ingest_text("Hello world. This is a test document.", title="test_doc")
            assert result["success"]
            assert result["chunk_count"] >= 1
            assert result["doc_id"]
            await kb.close()
        _run(go())

    def test_ingest_empty_text(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            result = await kb.ingest_text("")
            assert "error" in result
            await kb.close()
        _run(go())

    def test_ingest_file_txt(self, db_path, tmp_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            f = tmp_path / "sample.txt"
            f.write_text("This is a sample text file.\n\nIt has two paragraphs.")
            result = await kb.ingest(str(f))
            assert result["success"]
            assert result["doc_type"] == "text"
            await kb.close()
        _run(go())

    def test_ingest_file_csv(self, db_path, tmp_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            f = tmp_path / "data.csv"
            f.write_text("name,age\nAlice,30\nBob,25\n")
            result = await kb.ingest(str(f))
            assert result["success"]
            assert result["doc_type"] == "csv"
            await kb.close()
        _run(go())

    def test_ingest_file_html(self, db_path, tmp_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            f = tmp_path / "page.html"
            f.write_text("<html><body><p>Hello</p><p>World</p></body></html>")
            result = await kb.ingest(str(f))
            assert result["success"]
            assert result["doc_type"] == "html"
            await kb.close()
        _run(go())

    def test_ingest_missing_file(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            result = await kb.ingest("/nonexistent/file.txt")
            assert "error" in result
            await kb.close()
        _run(go())


class TestSearch:
    def test_search_returns_results(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            await kb.ingest_text(
                "Python is a programming language. It was created by Guido van Rossum.",
                title="python_doc",
            )
            results = await kb.search("programming language", top_k=3)
            assert len(results) >= 1
            assert isinstance(results[0], KBSearchResult)
            assert results[0].score > 0
            await kb.close()
        _run(go())

    def test_search_empty_kb(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            results = await kb.search("anything")
            assert results == []
            await kb.close()
        _run(go())

    def test_search_filters_weak_matches(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            await kb.ingest_text(
                "Python async workflows, sqlite storage, and retrieval pipelines.",
                title="python_doc",
            )
            await kb.ingest_text(
                "Tomatoes grow best in warm soil with compost and regular watering.",
                title="gardening_doc",
            )
            results = await kb.search("python retrieval", top_k=5)
            assert results
            assert all(result.score >= kb._min_similarity_score for result in results)
            await kb.close()
        _run(go())


class TestDocumentManagement:
    def test_list_documents(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            await kb.ingest_text("Document one", title="doc1")
            await kb.ingest_text("Document two", title="doc2")
            docs = await kb.list_documents()
            assert len(docs) == 2
            assert all(isinstance(d, KBDocument) for d in docs)
            await kb.close()
        _run(go())

    def test_delete_document(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            result = await kb.ingest_text("Temporary document", title="temp")
            doc_id = result["doc_id"]
            assert await kb.delete_document(doc_id)
            docs = await kb.list_documents()
            assert len(docs) == 0
            await kb.close()
        _run(go())

    def test_delete_nonexistent(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            assert not await kb.delete_document("nonexistent_id")
            await kb.close()
        _run(go())

    def test_get_document_chunks(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            result = await kb.ingest_text("A short document.", title="short")
            doc_id = result["doc_id"]
            chunks = await kb.get_document_chunks(doc_id)
            assert len(chunks) >= 1
            assert chunks[0].content == "A short document."
            await kb.close()
        _run(go())


class TestChunking:
    def test_large_text_is_chunked(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=100, overlap=10)
            await kb.initialize()
            large_text = "\n\n".join(f"Paragraph {i}. " * 10 for i in range(20))
            result = await kb.ingest_text(large_text, title="large")
            assert result["chunk_count"] > 1
            await kb.close()
        _run(go())

    def test_single_paragraph_within_limit(self, db_path):
        async def go():
            kb = KnowledgeBase(db_path=db_path, chunk_size=200, overlap=20)
            await kb.initialize()
            result = await kb.ingest_text("Short text.", title="short")
            assert result["chunk_count"] == 1
            await kb.close()
        _run(go())
