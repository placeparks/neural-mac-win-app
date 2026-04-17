import { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '../components/layout/Header';
import {
  clearMemory,
  deleteMemoryItem,
  exportMemoryBackup,
  getMemoryItems,
  getMemoryStats,
  importMemoryBackup,
  pinMemoryItem,
  runMemoryRetention,
  updateMemoryItem,
  type MemoryItem,
  type MemoryStats,
  type MemoryStore,
} from '../lib/api';

const MEMORY_STORES: Array<{ id: MemoryStore; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'episodic', label: 'Episodic' },
  { id: 'semantic', label: 'Semantic' },
  { id: 'procedural', label: 'Procedural' },
  { id: 'vector', label: 'Vector' },
  { id: 'identity', label: 'Identity' },
];

const WIPE_STORES: Exclude<MemoryStore, 'all'>[] = ['episodic', 'semantic', 'procedural', 'vector', 'identity'];

function formatTimestamp(value?: number | null) {
  if (!value) return 'Unknown';
  const timestamp = value > 1_000_000_000_000 ? value : value * 1000;
  return new Date(timestamp).toLocaleString();
}

function safeJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function storeLabel(store: MemoryStore) {
  return MEMORY_STORES.find((entry) => entry.id === store)?.label || store;
}

export default function MemoryPage() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [store, setStore] = useState<MemoryStore>('all');
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [wipeStores, setWipeStores] = useState<Record<Exclude<MemoryStore, 'all'>, boolean>>({
    episodic: true,
    semantic: true,
    procedural: true,
    vector: false,
    identity: false,
  });
  const [clearHistory, setClearHistory] = useState(true);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [backupPassphrase, setBackupPassphrase] = useState('');
  const [backupPayload, setBackupPayload] = useState('');
  const [backupEnvelope, setBackupEnvelope] = useState<{ encrypted: boolean; salt?: string; digest?: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStats, nextItems] = await Promise.all([
        getMemoryStats(),
        getMemoryItems(store, query, 80),
      ]);
      setStats(nextStats);
      setItems(nextItems.items || []);
      setSelectedKey((current) => {
        if (current && nextItems.items.some((item) => `${item.store}:${item.id}` === current)) return current;
        return nextItems.items[0] ? `${nextItems.items[0].store}:${nextItems.items[0].id}` : '';
      });
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to load memory data.' });
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [query, store]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedItem = useMemo(
    () => items.find((item) => `${item.store}:${item.id}` === selectedKey) || null,
    [items, selectedKey],
  );

  useEffect(() => {
    if (!selectedItem) {
      setDraft({});
      return;
    }
    if (selectedItem.store === 'episodic') {
      setDraft({
        content: selectedItem.content || '',
        importance: String(selectedItem.metadata.importance ?? ''),
        tags: Array.isArray(selectedItem.metadata.tags) ? selectedItem.metadata.tags.join(', ') : '',
      });
      return;
    }
    if (selectedItem.store === 'semantic') {
      setDraft({
        name: selectedItem.title,
        entity_type: String(selectedItem.metadata.entity_type || ''),
        attributes: safeJson(selectedItem.metadata.attributes || {}),
      });
      return;
    }
    if (selectedItem.store === 'procedural') {
      setDraft({
        name: selectedItem.title,
        description: selectedItem.preview || '',
        trigger_patterns: Array.isArray(selectedItem.metadata.trigger_patterns)
          ? selectedItem.metadata.trigger_patterns.join(', ')
          : '',
      });
      return;
    }
    if (selectedItem.store === 'identity') {
      setDraft({
        display_name: selectedItem.title,
        notes: selectedItem.content || '',
        language: String(selectedItem.metadata.language || ''),
        timezone: String(selectedItem.metadata.timezone || ''),
      });
      return;
    }
    setDraft({});
  }, [selectedItem]);

  const handleSave = async () => {
    if (!selectedItem || !selectedItem.can_edit || selectedItem.store === 'vector' || selectedItem.store === 'all') return;
    setSaving(true);
    setMessage(null);
    try {
      let payload: Record<string, unknown> = {};
      if (selectedItem.store === 'episodic') {
        payload = {
          content: draft.content,
          importance: draft.importance === '' ? undefined : Number(draft.importance),
          tags: String(draft.tags || '')
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean),
        };
      } else if (selectedItem.store === 'semantic') {
        payload = {
          name: draft.name,
          entity_type: draft.entity_type,
          attributes: draft.attributes ? JSON.parse(draft.attributes) : {},
        };
      } else if (selectedItem.store === 'procedural') {
        payload = {
          name: draft.name,
          description: draft.description,
          trigger_patterns: String(draft.trigger_patterns || '')
            .split(',')
            .map((pattern) => pattern.trim())
            .filter(Boolean),
        };
      } else if (selectedItem.store === 'identity') {
        payload = {
          display_name: draft.display_name,
          notes: draft.notes,
          language: draft.language,
          timezone: draft.timezone,
        };
      }
      const result = await updateMemoryItem(selectedItem.store as Exclude<MemoryStore, 'all' | 'vector'>, selectedItem.id, payload);
      if (!result.ok) throw new Error(result.error || 'Failed to update memory item.');
      setMessage({ ok: true, text: `${storeLabel(selectedItem.store)} item updated.` });
      await load();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to update memory item.' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedItem || !selectedItem.can_delete || selectedItem.store === 'all') return;
    if (!window.confirm(`Delete this ${selectedItem.store} memory item?`)) return;
    try {
      const result = await deleteMemoryItem(selectedItem.store as Exclude<MemoryStore, 'all'>, selectedItem.id);
      if (!result.ok) throw new Error(result.error || 'Failed to delete memory item.');
      setMessage({ ok: true, text: `${storeLabel(selectedItem.store)} item deleted.` });
      await load();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to delete memory item.' });
    }
  };

  const handlePin = async () => {
    if (!selectedItem || !selectedItem.can_pin || (selectedItem.store !== 'episodic' && selectedItem.store !== 'semantic')) return;
    try {
      const result = await pinMemoryItem(selectedItem.store, selectedItem.id);
      if (!result.ok) throw new Error(result.error || 'Failed to pin memory item.');
      setMessage({ ok: true, text: `${storeLabel(selectedItem.store)} item pinned.` });
      await load();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to pin memory item.' });
    }
  };

  const handleSelectiveClear = async () => {
    const stores = WIPE_STORES.filter((entry) => wipeStores[entry]);
    if (stores.length === 0) {
      setMessage({ ok: false, text: 'Select at least one memory store to wipe.' });
      return;
    }
    if (!window.confirm(`Delete selected memory stores: ${stores.join(', ')}?`)) return;
    try {
      const result = await clearMemory({ stores, clear_history: clearHistory });
      if (!result.ok) throw new Error('Failed to clear selected memory stores.');
      setMessage({
        ok: true,
        text: `Cleared ${result.episodic_deleted || 0} episodic, ${result.semantic_deleted || 0} semantic, ${result.procedural_deleted || 0} procedural, ${result.vector_deleted || 0} vector, ${result.identity_deleted || 0} identity records.`,
      });
      await load();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to clear memory stores.' });
    }
  };

  const handleExport = async () => {
    try {
      const stores = WIPE_STORES.filter((entry) => wipeStores[entry]);
      const result = await exportMemoryBackup({
        stores: stores.length ? stores : WIPE_STORES,
        passphrase: backupPassphrase.trim() || undefined,
      });
      if (!result.ok) throw new Error('Failed to export memory backup.');
      setBackupPayload(JSON.stringify(result, null, 2));
      setBackupEnvelope({
        encrypted: result.encrypted,
        salt: result.salt,
        digest: result.digest,
      });
      setMessage({ ok: true, text: result.encrypted ? 'Encrypted backup exported.' : 'Backup exported.' });
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to export memory backup.' });
    }
  };

  const handleImport = async () => {
    if (!backupPayload.trim()) {
      setMessage({ ok: false, text: 'Paste a backup payload first.' });
      return;
    }
    try {
      let parsedPayload = backupPayload.trim();
      let envelope = backupEnvelope;
      try {
        const parsed = JSON.parse(parsedPayload) as { payload?: string; encrypted?: boolean; salt?: string; digest?: string };
        if (parsed.payload) {
          parsedPayload = parsed.payload;
          envelope = {
            encrypted: Boolean(parsed.encrypted),
            salt: parsed.salt,
            digest: parsed.digest,
          };
        }
      } catch {
        // raw payload path
      }
      const result = await importMemoryBackup({
        payload: parsedPayload,
        encrypted: Boolean(envelope?.encrypted),
        salt: envelope?.salt,
        digest: envelope?.digest,
        passphrase: backupPassphrase.trim() || undefined,
      });
      if (!result.ok) throw new Error(result.error || 'Failed to import memory backup.');
      setMessage({ ok: true, text: `Imported backup: ${JSON.stringify(result.imported || {})}` });
      await load();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to import memory backup.' });
    }
  };

  const handleRunRetention = async () => {
    try {
      const result = await runMemoryRetention();
      if (!result.ok) throw new Error(result.error || 'Failed to run retention cleanup.');
      setMessage({ ok: true, text: `Retention cleanup deleted: ${JSON.stringify(result.deleted || {})}` });
      await load();
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to run retention cleanup.' });
    }
  };

  return (
    <>
      <Header title="Memory" />
      <div className="app-content">
        <div className="control-room memory-control-room">
          <section className="control-room-rail memory-rail">
            <div className="control-room-header">
              <div>
                <h1>Memory Control Center</h1>
                <p>Inspect, edit, pin, forget, and selectively wipe every persistent memory layer.</p>
              </div>
              <button className="btn btn-secondary" onClick={() => void load()}>
                Refresh
              </button>
            </div>

            <div className="memory-stats-grid">
              <div className="metric-card"><div className="metric-label">Episodic</div><div className="metric-value">{stats?.episodic_count ?? '-'}</div></div>
              <div className="metric-card"><div className="metric-label">Semantic</div><div className="metric-value">{stats?.semantic_count ?? '-'}</div></div>
              <div className="metric-card"><div className="metric-label">Procedural</div><div className="metric-value">{stats?.procedural_count ?? '-'}</div></div>
              <div className="metric-card"><div className="metric-label">Vector</div><div className="metric-value">{stats?.vector_count ?? '-'}</div></div>
              <div className="metric-card"><div className="metric-label">Identity</div><div className="metric-value">{stats?.identity_count ?? '-'}</div></div>
            </div>

            <div className="memory-store-tabs">
              {MEMORY_STORES.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  className={`memory-store-tab ${store === entry.id ? 'active' : ''}`}
                  onClick={() => setStore(entry.id)}
                >
                  <span>{entry.label}</span>
                  <span className="memory-store-tab-count">
                    {entry.id === 'all'
                      ? items.length
                      : entry.id === 'episodic'
                        ? (stats?.episodic_count ?? 0)
                        : entry.id === 'semantic'
                          ? (stats?.semantic_count ?? 0)
                          : entry.id === 'procedural'
                            ? (stats?.procedural_count ?? 0)
                            : entry.id === 'vector'
                              ? (stats?.vector_count ?? 0)
                              : (stats?.identity_count ?? 0)}
                  </span>
                </button>
              ))}
            </div>

            <div className="memory-search-row">
              <input
                className="input-field"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={`Search ${storeLabel(store).toLowerCase()} memory`}
              />
            </div>

            <div className="memory-wipe-card">
              <div className="task-detail-block-title">Selective Wipe</div>
              <div className="memory-wipe-grid">
                {WIPE_STORES.map((entry) => (
                  <label key={entry} className="memory-wipe-option">
                    <input
                      type="checkbox"
                      checked={wipeStores[entry]}
                      onChange={(event) => setWipeStores((current) => ({ ...current, [entry]: event.target.checked }))}
                    />
                    <span>{storeLabel(entry)}</span>
                  </label>
                ))}
              </div>
              <label className="memory-wipe-option">
                <input
                  type="checkbox"
                  checked={clearHistory}
                  onChange={(event) => setClearHistory(event.target.checked)}
                />
                <span>Clear in-memory conversation history</span>
              </label>
              <button className="btn btn-danger btn-sm" onClick={() => { void handleSelectiveClear(); }}>
                Wipe Selected
              </button>
            </div>

            <div className="memory-wipe-card">
              <div className="task-detail-block-title">Backup And Retention</div>
              <input
                className="input-field"
                type="password"
                value={backupPassphrase}
                onChange={(event) => setBackupPassphrase(event.target.value)}
                placeholder="Optional passphrase for encrypted export/import"
                style={{ marginBottom: 10 }}
              />
              <div className="memory-editor-actions">
                <button className="btn btn-secondary btn-sm" onClick={() => { void handleExport(); }}>
                  Export Backup
                </button>
                <button className="btn btn-secondary btn-sm" onClick={() => { void handleRunRetention(); }}>
                  Run Retention
                </button>
              </div>
              <textarea
                className="input-field memory-editor-textarea"
                value={backupPayload}
                onChange={(event) => setBackupPayload(event.target.value)}
                placeholder="Backup payload appears here for copy/paste import or export."
                style={{ marginTop: 10 }}
              />
              <div className="memory-editor-actions">
                <button className="btn btn-primary btn-sm" onClick={() => { void handleImport(); }}>
                  Import Backup
                </button>
              </div>
            </div>

            <div className="task-list">
              {loading ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="spinner" style={{ width: 20, height: 20 }} />
                  <p>Loading memory items...</p>
                </div>
              ) : items.length === 0 ? (
                <div className="empty-state" style={{ padding: 24 }}>
                  <span className="empty-icon">MM</span>
                  <h3>No memory items found</h3>
                  <p>Try another store or search term.</p>
                </div>
              ) : (
                items.map((item) => (
                  <button
                    key={`${item.store}:${item.id}`}
                    type="button"
                    className={`task-card ${selectedKey === `${item.store}:${item.id}` ? 'active' : ''}`}
                    onClick={() => setSelectedKey(`${item.store}:${item.id}`)}
                  >
                    <div className="task-card-top">
                      <span className={`badge badge-${item.store === 'episodic' ? 'blue' : item.store === 'semantic' ? 'purple' : item.store === 'procedural' ? 'green' : item.store === 'identity' ? 'orange' : 'blue'}`}>
                        {storeLabel(item.store)}
                      </span>
                      {item.pinned ? <span className="badge">Pinned</span> : null}
                    </div>
                    <div className="task-card-title">{item.title}</div>
                    <div className="task-card-meta">
                      <span>{formatTimestamp(item.updated_at || item.timestamp)}</span>
                      <span>{item.score != null ? `score ${Number(item.score).toFixed(2)}` : ''}</span>
                    </div>
                    <div className="task-card-preview">{item.preview || item.content || 'No preview'}</div>
                  </button>
                ))
              )}
            </div>
          </section>

          <section className="control-room-detail">
            {!selectedItem ? (
              <div className="empty-state" style={{ padding: 32 }}>
                <span className="empty-icon">MM</span>
                <h3>Select a memory item</h3>
                <p>Review stored details, patch bad memory, pin critical facts, or forget stale state.</p>
              </div>
            ) : (
              <div className="task-detail-panel">
                <div className="task-detail-header">
                  <div>
                    <div className="task-detail-eyebrow">{storeLabel(selectedItem.store)} Memory</div>
                    <h2>{selectedItem.title}</h2>
                    <div className="task-detail-chips">
                      <span className="badge">{storeLabel(selectedItem.store)}</span>
                      {selectedItem.pinned ? <span className="badge">Pinned</span> : null}
                      {selectedItem.score != null ? <span className="badge">Score {Number(selectedItem.score).toFixed(2)}</span> : null}
                    </div>
                  </div>
                  <div className="task-detail-actions">
                    {selectedItem.can_pin ? (
                      <button className="btn btn-secondary" onClick={() => { void handlePin(); }}>
                        Pin
                      </button>
                    ) : null}
                    {selectedItem.can_delete ? (
                      <button className="btn btn-danger" onClick={() => { void handleDelete(); }}>
                        Forget
                      </button>
                    ) : null}
                  </div>
                </div>

                <div className="task-metrics-grid">
                  <div className="metric-card">
                    <div className="metric-label">Created</div>
                    <div className="metric-value">{formatTimestamp(selectedItem.timestamp)}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Updated</div>
                    <div className="metric-value">{formatTimestamp(selectedItem.updated_at)}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Editable</div>
                    <div className="metric-value">{selectedItem.can_edit ? 'Yes' : 'No'}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Store</div>
                    <div className="metric-value">{storeLabel(selectedItem.store)}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Scope</div>
                    <div className="metric-value">{String(selectedItem.metadata.scope || 'global')}</div>
                  </div>
                  <div className="metric-card">
                    <div className="metric-label">Retention</div>
                    <div className="metric-value">{String(selectedItem.metadata.retention_days || '-')} days</div>
                  </div>
                </div>

                {message ? (
                  <div className={`info-box ${message.ok ? 'success' : 'error'}`}>
                    <span>{message.text}</span>
                  </div>
                ) : null}

                <div className="task-detail-block">
                  <div className="task-detail-block-title">Inspector</div>
                  {selectedItem.store === 'episodic' && selectedItem.can_edit ? (
                    <div className="memory-editor-grid">
                      <label>
                        <span>Content</span>
                        <textarea className="input-field memory-editor-textarea" value={draft.content || ''} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} />
                      </label>
                      <label>
                        <span>Importance</span>
                        <input className="input-field" value={draft.importance || ''} onChange={(event) => setDraft((current) => ({ ...current, importance: event.target.value }))} />
                      </label>
                      <label>
                        <span>Tags</span>
                        <input className="input-field" value={draft.tags || ''} onChange={(event) => setDraft((current) => ({ ...current, tags: event.target.value }))} />
                      </label>
                    </div>
                  ) : null}

                  {selectedItem.store === 'semantic' && selectedItem.can_edit ? (
                    <div className="memory-editor-grid">
                      <label>
                        <span>Name</span>
                        <input className="input-field" value={draft.name || ''} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
                      </label>
                      <label>
                        <span>Entity Type</span>
                        <input className="input-field" value={draft.entity_type || ''} onChange={(event) => setDraft((current) => ({ ...current, entity_type: event.target.value }))} />
                      </label>
                      <label>
                        <span>Attributes JSON</span>
                        <textarea className="input-field memory-editor-textarea" value={draft.attributes || ''} onChange={(event) => setDraft((current) => ({ ...current, attributes: event.target.value }))} />
                      </label>
                    </div>
                  ) : null}

                  {selectedItem.store === 'procedural' && selectedItem.can_edit ? (
                    <div className="memory-editor-grid">
                      <label>
                        <span>Name</span>
                        <input className="input-field" value={draft.name || ''} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
                      </label>
                      <label>
                        <span>Description</span>
                        <textarea className="input-field memory-editor-textarea" value={draft.description || ''} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
                      </label>
                      <label>
                        <span>Trigger Patterns</span>
                        <input className="input-field" value={draft.trigger_patterns || ''} onChange={(event) => setDraft((current) => ({ ...current, trigger_patterns: event.target.value }))} />
                      </label>
                    </div>
                  ) : null}

                  {selectedItem.store === 'identity' && selectedItem.can_edit ? (
                    <div className="memory-editor-grid">
                      <label>
                        <span>Display Name</span>
                        <input className="input-field" value={draft.display_name || ''} onChange={(event) => setDraft((current) => ({ ...current, display_name: event.target.value }))} />
                      </label>
                      <label>
                        <span>Language</span>
                        <input className="input-field" value={draft.language || ''} onChange={(event) => setDraft((current) => ({ ...current, language: event.target.value }))} />
                      </label>
                      <label>
                        <span>Timezone</span>
                        <input className="input-field" value={draft.timezone || ''} onChange={(event) => setDraft((current) => ({ ...current, timezone: event.target.value }))} />
                      </label>
                      <label>
                        <span>Notes</span>
                        <textarea className="input-field memory-editor-textarea" value={draft.notes || ''} onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))} />
                      </label>
                    </div>
                  ) : null}

                  {!selectedItem.can_edit ? (
                    <pre className="task-detail-code">{selectedItem.content || selectedItem.preview || 'Read-only entry'}</pre>
                  ) : null}

                  {selectedItem.can_edit ? (
                    <div className="memory-editor-actions">
                      <button className="btn btn-primary" disabled={saving} onClick={() => { void handleSave(); }}>
                        {saving ? 'Saving...' : 'Save Changes'}
                      </button>
                    </div>
                  ) : null}
                </div>

                <div className="task-detail-block">
                  <div className="task-detail-block-title">Metadata</div>
                  <pre className="task-detail-code">{safeJson(selectedItem.metadata)}</pre>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
