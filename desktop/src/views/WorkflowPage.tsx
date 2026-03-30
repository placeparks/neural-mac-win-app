// NeuralClaw Desktop — Workflow Page
// Workflows are managed through NeuralClaw's workflow engine

import Header from '../components/layout/Header';

export default function WorkflowPage() {
  return (
    <>
      <Header title="Workflows" />
      <div className="app-content">
        <div className="page-header">
          <h1>⚡ Workflow Manager</h1>
          <p>Create and run multi-step task automations via chat commands.</p>
        </div>

        <div className="page-body">
          <div className="info-box" style={{ marginBottom: 24 }}>
            <span className="info-icon">ℹ️</span>
            <span>
              Workflows are powered by NeuralClaw's Workflow Engine.
              Create and manage them through chat or the config file.
            </span>
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <span className="card-title">Quick Commands</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                { cmd: 'create workflow "daily_report"', desc: 'Create a new workflow' },
                { cmd: 'run workflow daily_report', desc: 'Execute a workflow' },
                { cmd: 'list workflows', desc: 'See all available workflows' },
                { cmd: 'workflow status daily_report', desc: 'Check workflow execution status' },
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
