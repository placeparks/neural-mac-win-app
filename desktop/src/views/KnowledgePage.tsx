import { useCallback, useEffect, useRef, useState } from 'react';
import Header from '../components/layout/Header';
import {
  deleteKnowledgeDocument,
  getKnowledgeDocuments,
  ingestKnowledgeText,
  searchKnowledgeBase,
  type KBDocument,
  type KBSearchResult,
} from '../lib/api';

async function readKnowledgeFile(file: File): Promise<{ text: string; source: string; mimeType: string }> {
  if (file.type.startsWith('image/')) {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
      reader.readAsDataURL(file);
    });
    return {
      text: `Image asset uploaded: ${file.name}\n\nThis image was added from the desktop knowledge base uploader.`,
      source: dataUrl,
      mimeType: file.type || 'image/png',
    };
  }

  const text = await file.text();
  return {
    text,
    source: file.name,
    mimeType: file.type || 'text/plain',
  };
}

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<KBDocument[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KBSearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [selectedFileName, setSelectedFileName] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getKnowledgeDocuments();
      setDocuments(next);
      setMessage(null);
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to load knowledge base documents.' });
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const handleFileUpload = async (file: File | null) => {
    if (!file) return;
    setIngesting(true);
    setMessage(null);
    setSelectedFileName(file.name);
    try {
      const payload = await readKnowledgeFile(file);
      const result = await ingestKnowledgeText({
        title: file.name,
        text: payload.text,
        source: payload.source,
        mimeType: payload.mimeType,
        content: payload.text,
      });
      if (!result.ok) {
        setMessage({ ok: false, text: result.error || 'Knowledge ingest failed.' });
      } else {
        setMessage({ ok: true, text: `Ingested ${result.filename || file.name} into the knowledge base.` });
        await loadDocuments();
      }
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to read the selected file.' });
    } finally {
      setIngesting(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setMessage(null);
    try {
      const results = await searchKnowledgeBase(searchQuery.trim());
      setSearchResults(results);
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Knowledge search failed.' });
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const handleDelete = async (documentId: string) => {
    try {
      const result = await deleteKnowledgeDocument(documentId);
      if (!result.ok) {
        setMessage({ ok: false, text: 'Failed to delete document.' });
        return;
      }
      await loadDocuments();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to delete document.' });
    }
  };

  return (
    <>
      <Header title="Knowledge Base" />
      <div className="app-content">
        <div className="page-header">
          <h1>Knowledge Base</h1>
          <p>Upload text, docs, JSON, CSV, markdown, or images so NeuralClaw can retrieve them later.</p>
        </div>

        <div className="page-body">
          {message && (
            <div
              className="info-box"
              style={{
                marginBottom: 16,
                background: message.ok ? 'var(--accent-green-muted)' : 'var(--accent-red-muted)',
                borderColor: message.ok ? 'rgba(63, 185, 80, 0.3)' : 'rgba(248, 81, 73, 0.3)',
              }}
            >
              <span className="info-icon">{message.ok ? '✓' : '!'}</span>
              <span>{message.text}</span>
            </div>
          )}

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Upload to Knowledge Base</span>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                className="btn btn-primary"
                onClick={() => fileInputRef.current?.click()}
                disabled={ingesting}
              >
                {ingesting ? 'Uploading...' : 'Choose File'}
              </button>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                {selectedFileName || 'Supports text, markdown, csv, json, html, and images.'}
              </span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept="image/*,.txt,.md,.markdown,.csv,.json,.html,.htm,.xml"
              onChange={(event) => {
                const file = event.target.files?.[0] || null;
                void handleFileUpload(file);
                event.currentTarget.value = '';
              }}
            />
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Search Knowledge Base</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="input-field"
                placeholder="Search across ingested knowledge..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void handleSearch();
                  }
                }}
              />
              <button className="btn btn-secondary" onClick={() => { void handleSearch(); }} disabled={searching || !searchQuery.trim()}>
                {searching ? 'Searching...' : 'Search'}
              </button>
            </div>

            {searchResults.length > 0 && (
              <div style={{ display: 'grid', gap: 10, marginTop: 14 }}>
                {searchResults.map((result, index) => (
                  <div key={`${result.document}-${result.chunk_index}-${index}`} className="card" style={{ padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
                      <strong>{result.document}</strong>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{(result.score * 100).toFixed(1)}%</span>
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                      {result.content}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-header">
              <span className="card-title">Documents ({documents.length})</span>
              <button className="btn btn-secondary btn-sm" onClick={() => { void loadDocuments(); }}>
                Refresh
              </button>
            </div>

            {loading ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
                <div className="spinner spinner-lg" />
              </div>
            ) : documents.length === 0 ? (
              <div className="empty-state" style={{ padding: 24 }}>
                <span className="empty-icon">K</span>
                <h3>No Knowledge Added Yet</h3>
                <p>Upload a document or image above to start building the desktop knowledge base.</p>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 8 }}>
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-sm)',
                      background: 'var(--bg-tertiary)',
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>{doc.filename}</div>
                      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-muted)' }}>
                        <span>{doc.doc_type}</span>
                        <span>{doc.chunk_count} chunks</span>
                        <span>{new Date(doc.ingested_at * 1000).toLocaleString()}</span>
                      </div>
                    </div>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => {
                        if (window.confirm(`Delete ${doc.filename} from the knowledge base?`)) {
                          void handleDelete(doc.id);
                        }
                      }}
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
