// NeuralClaw Desktop — Knowledge Base Page (Full Implementation)

import { useState, useEffect, useCallback } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';

interface KBDocument {
  id: string;
  filename: string;
  source: string;
  doc_type: string;
  ingested_at: string;
  chunk_count: number;
}

interface KBSearchResult {
  content: string;
  document: string;
  score: number;
  chunk_index: number;
}

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<KBDocument[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KBSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestPath, setIngestPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadDocuments = useCallback(async () => {
    try {
      const result = await invoke<string>('get_kb_documents');
      const parsed = JSON.parse(result);
      setDocuments(Array.isArray(parsed) ? parsed : parsed.documents || []);
      setError(null);
    } catch (err) {
      setError('Could not load documents. Is the backend running?');
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const result = await invoke<string>('search_kb', { query: searchQuery });
      const parsed = JSON.parse(result);
      setSearchResults(Array.isArray(parsed) ? parsed : parsed.results || []);
    } catch (err) {
      setError('Search failed. Check backend connection.');
    } finally {
      setSearching(false);
    }
  };

  const handleIngest = async () => {
    if (!ingestPath.trim()) return;
    setIngesting(true);
    setError(null);
    try {
      await invoke<string>('ingest_kb_document', { filePath: ingestPath });
      setIngestPath('');
      await loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ingestion failed.');
    } finally {
      setIngesting(false);
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      await invoke<string>('delete_kb_document', { documentId: docId });
      await loadDocuments();
    } catch (err) {
      setError('Failed to delete document.');
    }
  };

  return (
    <>
      <Header title="Knowledge Base" />
      <div className="app-content">
        <div className="page-header">
          <h1>📚 Knowledge Base</h1>
          <p>Upload and search documents to give NeuralClaw context about your data.</p>
        </div>

        <div className="page-body">
          {error && (
            <div className="info-box" style={{ background: 'var(--accent-red-muted)', borderColor: 'rgba(248,81,73,0.3)', marginBottom: 16 }}>
              <span className="info-icon">!</span>
              <span>{error}</span>
            </div>
          )}

          {/* Ingest Section */}
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Ingest Document</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="input-field input-mono"
                type="text"
                placeholder="File path (e.g., ~/documents/report.pdf)"
                value={ingestPath}
                onChange={(e) => setIngestPath(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleIngest()}
                style={{ flex: 1 }}
              />
              <button
                className="btn btn-primary"
                onClick={handleIngest}
                disabled={!ingestPath.trim() || ingesting}
              >
                {ingesting ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Ingesting...</> : 'Ingest'}
              </button>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
              Supported: .txt, .md, .html, .csv, .pdf
            </div>
          </div>

          {/* Search Section */}
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Search Knowledge Base</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="input-field"
                type="text"
                placeholder="Search query..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                style={{ flex: 1 }}
              />
              <button
                className="btn btn-secondary"
                onClick={handleSearch}
                disabled={!searchQuery.trim() || searching}
              >
                {searching ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Searching...</> : 'Search'}
              </button>
            </div>

            {searchResults.length > 0 && (
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{searchResults.length} result(s)</div>
                {searchResults.map((r, i) => (
                  <div key={i} style={{
                    padding: '10px 14px', background: 'var(--bg-tertiary)',
                    borderRadius: 'var(--radius-sm)', fontSize: 13,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{r.document}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Score: {(r.score * 100).toFixed(1)}%</span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                      {r.content.length > 300 ? r.content.slice(0, 300) + '...' : r.content}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Documents List */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Documents ({documents.length})</span>
              <button className="btn btn-ghost btn-sm" onClick={loadDocuments}>Refresh</button>
            </div>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 20, color: 'var(--text-muted)' }}>
                <span className="spinner" style={{ width: 20, height: 20 }} /> Loading...
              </div>
            ) : documents.length === 0 ? (
              <div className="empty-state" style={{ padding: 24 }}>
                <span className="empty-icon">📄</span>
                <h3>No Documents</h3>
                <p>Ingest documents above to build your knowledge base.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {documents.map((doc) => (
                  <div key={doc.id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 14px', background: 'var(--bg-tertiary)',
                    borderRadius: 'var(--radius-sm)',
                  }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>{doc.filename}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 12 }}>
                        <span>{doc.doc_type.toUpperCase()}</span>
                        <span>{doc.chunk_count} chunks</span>
                        <span>{new Date(doc.ingested_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDelete(doc.id)}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
