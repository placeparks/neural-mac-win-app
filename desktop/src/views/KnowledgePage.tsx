// NeuralClaw Desktop — Knowledge Base Page
// KB features are accessed through the dashboard and skills system

import Header from '../components/layout/Header';

export default function KnowledgePage() {
  return (
    <>
      <Header title="Knowledge Base" />
      <div className="app-content">
        <div className="page-header">
          <h1>📚 Knowledge Base</h1>
          <p>Upload and search documents to give NeuralClaw context about your data.</p>
        </div>

        <div className="page-body">
          <div className="info-box" style={{ marginBottom: 24 }}>
            <span className="info-icon">ℹ️</span>
            <span>
              Knowledge Base is managed through NeuralClaw's skill system.
              Use the chat to ask NeuralClaw to ingest or search documents.
            </span>
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Quick Commands</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                { cmd: 'ingest ~/documents/report.pdf', desc: 'Ingest a document into the KB' },
                { cmd: 'search kb: "quarterly revenue"', desc: 'Search the knowledge base' },
                { cmd: 'list kb documents', desc: 'List all ingested documents' },
              ].map((item) => (
                <div key={item.cmd} style={{
                  padding: '10px 14px', background: 'var(--bg-tertiary)',
                  borderRadius: 'var(--radius-sm)', fontFamily: 'var(--font-mono)', fontSize: 13,
                }}>
                  <span style={{ color: 'var(--accent-blue)' }}>→ </span>
                  <span style={{ color: 'var(--text-primary)' }}>{item.cmd}</span>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{item.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
