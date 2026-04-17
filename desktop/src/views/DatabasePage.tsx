import { useCallback, useEffect, useMemo, useState } from 'react';
import Header from '../components/layout/Header';
import {
  getDBConnections,
  connectDB,
  disconnectDB,
  getDBTables,
  queryDB,
  naturalQueryDB,
  chartDB,
  getConfig,
  getProviderModels,
  getProviderStatus,
  updateDashboardConfig,
  type DBConnection,
  type ModelOption,
} from '../lib/api';
import { getPersistedValue, setPersistedValue } from '../lib/persistence';

const ACTIVE_CONN_KEY = 'neuralclaw.db.activeConnection';
const QUERY_DRAFTS_KEY = 'neuralclaw.db.queryDrafts';
const QUERY_HISTORY_KEY = 'neuralclaw.db.queryHistory';

type QueryMode = 'sql' | 'natural' | 'chart';

type QueryHistoryItem = {
  connection: string;
  mode: QueryMode;
  input: string;
  createdAt: number;
};

type DBRouteState = {
  provider: string;
  model: string;
  baseUrl: string;
  allowFallback: boolean;
};

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

export default function DatabasePage() {
  const [connections, setConnections] = useState<DBConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const [showConnectForm, setShowConnectForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formDriver, setFormDriver] = useState('sqlite');
  const [formDSN, setFormDSN] = useState('');
  const [formSchema, setFormSchema] = useState('');
  const [formReadOnly, setFormReadOnly] = useState(true);
  const [connecting, setConnecting] = useState(false);

  const [activeConn, setActiveConn] = useState('');
  const [queryMode, setQueryMode] = useState<QueryMode>('natural');
  const [queryInput, setQueryInput] = useState('');
  const [queryResult, setQueryResult] = useState('');
  const [querying, setQuerying] = useState(false);
  const [chartType, setChartType] = useState('bar');
  const [chartImage, setChartImage] = useState('');
  const [tablesResult, setTablesResult] = useState('');
  const [history, setHistory] = useState<QueryHistoryItem[]>([]);
  const [routeConfig, setRouteConfig] = useState<DBRouteState>({
    provider: 'primary',
    model: '',
    baseUrl: '',
    allowFallback: false,
  });
  const [providerModels, setProviderModels] = useState<ModelOption[]>([]);
  const [providerChoices, setProviderChoices] = useState<Array<{ name: string; configured: boolean }>>([]);
  const [providerLoading, setProviderLoading] = useState(false);
  const [providerSaving, setProviderSaving] = useState(false);

  const activeConnection = useMemo(
    () => connections.find((conn) => conn.name === activeConn) || null,
    [activeConn, connections],
  );

  const draftKey = `${activeConn || 'none'}:${queryMode}`;

  const persistHistory = useCallback((items: QueryHistoryItem[]) => {
    setHistory(items);
    void setPersistedValue(QUERY_HISTORY_KEY, items);
  }, []);

  const loadConnections = useCallback(async () => {
    setLoading(true);
    try {
      const conns = await getDBConnections();
      setConnections(conns);
      if (conns.length === 0) {
        setActiveConn('');
        return;
      }
      const persisted = conns.some((conn) => conn.name === activeConn);
      const nextConn = persisted ? activeConn : conns[0].name;
      setActiveConn(nextConn);
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to load connections' });
    } finally {
      setLoading(false);
    }
  }, [activeConn]);

  useEffect(() => {
    void loadConnections();
  }, [loadConnections]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      getPersistedValue<string>(ACTIVE_CONN_KEY, ''),
      getPersistedValue<QueryHistoryItem[]>(QUERY_HISTORY_KEY, []),
    ]).then(([savedConnection, savedHistory]) => {
      if (cancelled) return;
      setActiveConn(savedConnection || '');
      setHistory(savedHistory);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadRouteConfig = async () => {
      try {
        const [cfg, providerSnapshot] = await Promise.all([
          getConfig(),
          getProviderStatus().catch(() => ({ providers: [] })),
        ]);
        const dbConfig = asRecord(asRecord(cfg).database_bi);
        const providers = asRecord(asRecord(cfg).providers);
        const provider = String(dbConfig.workspace_provider || 'primary');
        const primaryProvider = String(providers.primary || (providerSnapshot as { primary?: string }).primary || 'primary');
        const resolvedProvider = provider === 'primary' ? primaryProvider : provider;
        const providerConfig = asRecord(providers[resolvedProvider]);
        if (!cancelled) {
          setRouteConfig({
            provider,
            model: String(dbConfig.workspace_model || ''),
            baseUrl: String(dbConfig.workspace_base_url || providerConfig.base_url || ''),
            allowFallback: Boolean(dbConfig.workspace_allow_fallback ?? false),
          });
          setProviderChoices(
            [
              { name: 'primary', configured: true },
              ...((providerSnapshot.providers || []) as Array<{ name: string; configured?: boolean }>)
                .filter((entry) => entry.name !== 'meta')
                .map((entry) => ({ name: entry.name, configured: Boolean(entry.configured) })),
            ],
          );
        }
      } catch {
        if (!cancelled) {
          setRouteConfig((current) => ({ ...current }));
        }
      }
    };
    void loadRouteConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeConn) return;
    void setPersistedValue(ACTIVE_CONN_KEY, activeConn);
    void getPersistedValue<Record<string, string>>(QUERY_DRAFTS_KEY, {}).then((drafts) => {
      setQueryInput(drafts[draftKey] || '');
    });
  }, [activeConn, draftKey]);

  useEffect(() => {
    void getPersistedValue<Record<string, string>>(QUERY_DRAFTS_KEY, {}).then((drafts) => {
      const nextDrafts = { ...drafts, [draftKey]: queryInput };
      void setPersistedValue(QUERY_DRAFTS_KEY, nextDrafts);
    });
  }, [draftKey, queryInput]);

  useEffect(() => {
    const selectedProvider = routeConfig.provider;
    if (!selectedProvider || selectedProvider === 'primary') {
      setProviderModels([]);
      return;
    }

    let cancelled = false;
    setProviderLoading(true);
    getProviderModels(selectedProvider, routeConfig.baseUrl || undefined)
      .then((models) => {
        if (!cancelled) setProviderModels(models);
      })
      .catch(() => {
        if (!cancelled) setProviderModels([]);
      })
      .finally(() => {
        if (!cancelled) setProviderLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [routeConfig.provider, routeConfig.baseUrl]);

  const saveRouteConfig = async () => {
    setProviderSaving(true);
    try {
      const result = await updateDashboardConfig({
        database_bi: {
          workspace_provider: routeConfig.provider,
          workspace_model: routeConfig.model,
          workspace_base_url: routeConfig.baseUrl,
          workspace_allow_fallback: routeConfig.allowFallback,
        },
      });
      if (!result.ok) {
        setMessage({ ok: false, text: result.error || 'Failed to save DB AI route' });
        return;
      }
      setMessage({
        ok: true,
        text: routeConfig.allowFallback
          ? 'Database AI route saved with fallback enabled.'
          : 'Database AI route saved. Natural-language analysis will stay on the selected provider unless you change it.',
      });
    } finally {
      setProviderSaving(false);
    }
  };

  const queryRoute = useMemo(() => ({
    provider: routeConfig.provider === 'primary' ? undefined : routeConfig.provider,
    model: routeConfig.model || undefined,
    base_url: routeConfig.baseUrl || undefined,
    allow_fallback: routeConfig.allowFallback,
  }), [routeConfig]);

  const handleConnect = async () => {
    if (!formName || !formDSN) {
      setMessage({ ok: false, text: 'Name and DSN are required.' });
      return;
    }
    setConnecting(true);
    setMessage(null);
    try {
      const result = await connectDB({
        name: formName,
        driver: formDriver,
        dsn: formDSN,
        schema: formSchema || undefined,
        read_only: formReadOnly,
      });
      setMessage({ ok: result.ok, text: result.message });
      if (result.ok) {
        setShowConnectForm(false);
        setFormName('');
        setFormDSN('');
        setFormSchema('');
        setActiveConn(formName);
        await loadConnections();
      }
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Connection failed' });
    } finally {
      setConnecting(false);
    }
  };

  const handleDisconnect = async (name: string) => {
    try {
      await disconnectDB(name);
      if (activeConn === name) {
        setActiveConn('');
        setTablesResult('');
        setQueryResult('');
        setChartImage('');
      }
      await loadConnections();
      setMessage({ ok: true, text: `Disconnected from '${name}'. The saved profile was removed too.` });
    } catch (error: any) {
      setMessage({ ok: false, text: error?.message || 'Failed to disconnect' });
    }
  };

  const handleLoadTables = useCallback(async () => {
    if (!activeConn) return;
    try {
      const result = await getDBTables(activeConn);
      setTablesResult(result.result || 'No tables found.');
    } catch (error: any) {
      setTablesResult(`Error: ${error?.message || 'Failed to load tables'}`);
    }
  }, [activeConn]);

  useEffect(() => {
    void handleLoadTables();
  }, [handleLoadTables]);

  const handleQuery = async () => {
    if (!activeConn || !queryInput.trim()) return;
    setQuerying(true);
    setQueryResult('');
    setChartImage('');
    try {
      if (queryMode === 'sql') {
        const result = await queryDB(activeConn, queryInput);
        setQueryResult(result.result || 'No results.');
      } else if (queryMode === 'natural') {
        const result = await naturalQueryDB(activeConn, queryInput, queryRoute);
        setQueryResult(result.result || 'No results.');
      } else {
        const result = await chartDB({
          connection: activeConn,
          query: queryInput,
          chart_type: chartType,
          ...queryRoute,
        });
        const raw = result.result || '';
        setQueryResult(typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2));
        if (typeof raw === 'object' && raw && 'image_base64' in (raw as Record<string, unknown>)) {
          setChartImage(String((raw as Record<string, unknown>).image_base64 || ''));
        }
      }
      persistHistory([
        {
          connection: activeConn,
          mode: queryMode,
          input: queryInput.trim(),
          createdAt: Date.now(),
        },
        ...history,
      ].slice(0, 10));
    } catch (error: any) {
      setQueryResult(`Error: ${error?.message || 'Query failed'}`);
    } finally {
      setQuerying(false);
    }
  };

  const driverOptions = [
    { value: 'sqlite', label: 'SQLite', hint: '~/data/mydb.db' },
    { value: 'postgres', label: 'PostgreSQL', hint: 'postgresql://user:pass@host:5432/db' },
    { value: 'mysql', label: 'MySQL', hint: 'mysql://user:pass@host:3306/db' },
    { value: 'mongodb', label: 'MongoDB', hint: 'mongodb://host:27017/db' },
    { value: 'clickhouse', label: 'ClickHouse', hint: 'http://host:8123' },
  ];

  const recentItems = history.filter((item) => item.connection === activeConn).slice(0, 4);
  const selectedDriverHint = driverOptions.find((d) => d.value === formDriver)?.hint || '';

  return (
    <div className="view-container">
      <Header title="Database BI" subtitle="Persistent database workbench with natural-language analysis and charting" />
      <div className="page-body" style={{ paddingTop: 16 }}>
        {message && (
          <div className={`status-banner ${message.ok ? 'status-success' : 'status-error'}`}>
            {message.text}
          </div>
        )}

        <section className="card db-hero-card" style={{ marginBottom: 16 }}>
          <div className="db-hero-top">
            <div>
              <div className="eyebrow">Persistent Database Workspace</div>
              <h2 style={{ margin: '6px 0 8px' }}>{activeConnection ? activeConnection.name : 'Bring your data into NeuralClaw'}</h2>
              <p className="db-hero-copy">
                Active DB sessions now stay saved for the user. Once connected, the database becomes a standing workspace with schema context, sticky drafts, and recent analysis prompts.
              </p>
            </div>
            <button className="btn btn-primary" onClick={() => setShowConnectForm((value) => !value)}>
              {showConnectForm ? 'Close Connect Form' : 'Connect Database'}
            </button>
          </div>
          <div className="db-metric-grid">
            <div className="db-metric-card">
              <span className="db-metric-label">Saved Connections</span>
              <strong>{connections.filter((conn) => conn.persisted).length}</strong>
            </div>
            <div className="db-metric-card">
              <span className="db-metric-label">Live Tables</span>
              <strong>{activeConnection?.table_count || 0}</strong>
            </div>
            <div className="db-metric-card">
              <span className="db-metric-label">Access Mode</span>
              <strong>{activeConnection?.read_only ? 'Read-only' : 'Read-write'}</strong>
            </div>
            <div className="db-metric-card">
              <span className="db-metric-label">Query Memory</span>
              <strong>{recentItems.length} recent prompts</strong>
            </div>
          </div>
        </section>

        <section className="card" style={{ marginBottom: 16 }}>
          <div className="db-section-head">
            <div>
              <div className="eyebrow">AI Analyst Route</div>
              <h3 style={{ margin: '6px 0' }}>Control which model reads your database</h3>
            </div>
            <span className="badge">{routeConfig.allowFallback ? 'fallback enabled' : 'locked route'}</span>
          </div>
          <p style={{ color: 'var(--text-muted)', marginTop: 0 }}>
            Natural-language DB analysis no longer has to collapse to local by default. Pick the provider and model that should own this workspace, including Vercel AI Gateway if you have it connected.
          </p>
          <div className="db-connect-grid">
            <div>
              <label className="field-label">Provider</label>
              <select
                className="input"
                value={routeConfig.provider}
                onChange={(e) => setRouteConfig((current) => ({ ...current, provider: e.target.value }))}
              >
                {providerChoices.map((option) => (
                  <option key={option.name} value={option.name}>
                    {option.name === 'primary' ? 'Primary provider (from Settings)' : `${option.name}${option.configured ? '' : ' (not configured)'}`}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="field-label">Model</label>
              <select
                className="input"
                value={routeConfig.model}
                onChange={(e) => setRouteConfig((current) => ({ ...current, model: e.target.value }))}
              >
                <option value="">Use provider default</option>
                {providerModels.map((model) => (
                  <option key={model.name} value={model.name}>{model.name}</option>
                ))}
              </select>
              <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 6 }}>
                {providerLoading ? 'Loading models…' : providerModels.length > 0 ? `${providerModels.length} models available` : 'Enter a base URL or save the provider first if models do not load.'}
              </div>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <label className="field-label">Base URL Override</label>
            <input
              className="input"
              value={routeConfig.baseUrl}
              onChange={(e) => setRouteConfig((current) => ({ ...current, baseUrl: e.target.value }))}
              placeholder="Leave blank to use the provider default"
              style={{ width: '100%' }}
            />
          </div>
          <label className="db-checkbox-row" style={{ marginTop: 12 }}>
            <input
              type="checkbox"
              checked={routeConfig.allowFallback}
              onChange={(e) => setRouteConfig((current) => ({ ...current, allowFallback: e.target.checked }))}
            />
            <span>Allow fallback when the selected route is unavailable</span>
          </label>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
            <button className="btn btn-secondary" onClick={() => setRouteConfig({ provider: 'primary', model: '', baseUrl: '', allowFallback: false })}>
              Lock To Primary
            </button>
            <button className="btn btn-secondary" onClick={() => setRouteConfig({ provider: 'vercel', model: 'openai/gpt-5.4', baseUrl: 'https://ai-gateway.vercel.sh/v1', allowFallback: false })}>
              Use Vercel AI Gateway
            </button>
            <button className="btn btn-primary" onClick={() => { void saveRouteConfig(); }} disabled={providerSaving}>
              {providerSaving ? 'Saving…' : 'Save DB AI Route'}
            </button>
          </div>
        </section>

        <section className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Connection Deck</h3>
            <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Click a connection to pin it as the active workspace.</span>
          </div>

          {showConnectForm && (
            <div className="db-connect-form">
              <div className="db-connect-grid">
                <div>
                  <label className="field-label">Name</label>
                  <input className="input" placeholder="e.g. sales_db" value={formName} onChange={(e) => setFormName(e.target.value)} />
                </div>
                <div>
                  <label className="field-label">Driver</label>
                  <select className="input" value={formDriver} onChange={(e) => setFormDriver(e.target.value)}>
                    {driverOptions.map((driver) => (
                      <option key={driver.value} value={driver.value}>{driver.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div style={{ marginBottom: 10 }}>
                <label className="field-label">Connection String / Path</label>
                <input className="input" placeholder={selectedDriverHint} value={formDSN} onChange={(e) => setFormDSN(e.target.value)} style={{ width: '100%' }} />
              </div>
              <div className="db-connect-grid">
                <div>
                  <label className="field-label">Schema (optional)</label>
                  <input className="input" placeholder="public" value={formSchema} onChange={(e) => setFormSchema(e.target.value)} />
                </div>
                <label className="db-checkbox-row">
                  <input type="checkbox" checked={formReadOnly} onChange={(e) => setFormReadOnly(e.target.checked)} />
                  <span>Read-only and safe by default</span>
                </label>
              </div>
              <button className="btn btn-primary" onClick={handleConnect} disabled={connecting}>
                {connecting ? 'Connecting...' : 'Connect And Persist'}
              </button>
            </div>
          )}

          {loading ? (
            <div style={{ color: 'var(--text-muted)', padding: 12 }}>Loading connections...</div>
          ) : connections.length === 0 ? (
            <div className="empty-state" style={{ padding: 20 }}>
              <span className="empty-icon">DB</span>
              <h3>No database connections yet</h3>
              <p>Create one saved connection and NeuralClaw will keep it ready across relaunches.</p>
            </div>
          ) : (
            <div className="db-connection-grid">
              {connections.map((conn) => (
                <div
                  key={conn.name}
                  className={`db-connection-card ${activeConn === conn.name ? 'active' : ''}`}
                  onClick={() => setActiveConn(conn.name)}
                >
                  <div className="db-connection-top">
                    <strong>{conn.name}</strong>
                    <span className={`badge ${conn.persisted ? 'badge-green' : 'badge'}`}>{conn.persisted ? 'saved' : 'session'}</span>
                  </div>
                  <div className="db-connection-meta">
                    <span>{conn.driver}</span>
                    <span>{conn.table_count} tables</span>
                    <span>{conn.read_only ? 'read-only' : 'read-write'}</span>
                  </div>
                  <div className="db-connection-footer">
                    <span style={{ color: 'var(--text-muted)' }}>{conn.schema || conn.dsn_display || 'No schema set'}</span>
                    <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); void handleDisconnect(conn.name); }}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {activeConnection && (
          <div className="db-workbench-grid">
            <section className="card">
              <div className="db-section-head">
                <div>
                  <div className="eyebrow">Active Workspace</div>
                  <h3 style={{ margin: '6px 0' }}>{activeConnection.name}</h3>
                </div>
                <span className="badge">{activeConnection.persisted ? 'persisted for user' : 'live session'}</span>
              </div>
              <div className="db-inline-stats">
                <span>{activeConnection.driver}</span>
                <span>{activeConnection.table_count} tables</span>
                <span>{activeConnection.read_only ? 'read-only policy' : 'write enabled'}</span>
                <span>{routeConfig.provider === 'primary' ? 'AI route: primary' : `AI route: ${routeConfig.provider}`}</span>
              </div>
              <pre className="db-schema-preview">{tablesResult || 'Loading schema...'}</pre>
            </section>

            <section className="card">
              <div className="db-section-head">
                <div>
                  <div className="eyebrow">Query Studio</div>
                  <h3 style={{ margin: '6px 0' }}>Ask, inspect, chart</h3>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                {(['natural', 'sql', 'chart'] as const).map((mode) => (
                  <button
                    key={mode}
                    className={`btn btn-sm ${queryMode === mode ? 'btn-primary' : 'btn-ghost'}`}
                    onClick={() => setQueryMode(mode)}
                  >
                    {mode === 'natural' ? 'Natural Language' : mode === 'sql' ? 'Raw SQL' : 'Chart'}
                  </button>
                ))}
                {queryMode === 'chart' && (
                  <select className="input" value={chartType} onChange={(e) => setChartType(e.target.value)} style={{ width: 120, height: 32, fontSize: 12 }}>
                    <option value="bar">Bar</option>
                    <option value="line">Line</option>
                    <option value="pie">Pie</option>
                    <option value="scatter">Scatter</option>
                    <option value="heatmap">Heatmap</option>
                  </select>
                )}
              </div>
              <textarea
                className="input"
                rows={4}
                placeholder={
                  queryMode === 'natural'
                    ? 'Ask a business question, for example: Which customers dropped revenue this month?'
                    : queryMode === 'sql'
                      ? 'SELECT * FROM ...'
                      : 'Describe the chart you want, for example: monthly revenue trend by region'
                }
                value={queryInput}
                onChange={(e) => setQueryInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void handleQuery(); }}
                style={{ width: '100%', resize: 'vertical', marginBottom: 12 }}
              />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button className="btn btn-primary" onClick={() => { void handleQuery(); }} disabled={querying || !queryInput.trim()}>
                  {querying ? 'Running...' : queryMode === 'chart' ? 'Generate Chart' : 'Run Query'}
                </button>
                <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Drafts are sticky per connection and mode.</span>
              </div>

              {queryResult && (
                <pre className="db-query-result">{queryResult}</pre>
              )}
              {chartImage && (
                <div className="db-chart-shell">
                  <img src={`data:image/png;base64,${chartImage}`} alt="Database chart" style={{ maxWidth: '100%', borderRadius: 12 }} />
                </div>
              )}
            </section>
          </div>
        )}

        {activeConnection && (
          <section className="card" style={{ marginTop: 16 }}>
            <div className="db-section-head">
              <div>
                <div className="eyebrow">Recent Prompts</div>
                <h3 style={{ margin: '6px 0' }}>Resume where you left off</h3>
              </div>
            </div>
            {recentItems.length === 0 ? (
              <div style={{ color: 'var(--text-muted)' }}>No recent query prompts for this connection yet.</div>
            ) : (
              <div className="db-history-list">
                {recentItems.map((item) => (
                  <button
                    key={`${item.createdAt}-${item.input}`}
                    className="db-history-item"
                    onClick={() => {
                      setQueryMode(item.mode);
                      setQueryInput(item.input);
                    }}
                  >
                    <span className="badge">{item.mode}</span>
                    <span className="db-history-copy">{item.input}</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
