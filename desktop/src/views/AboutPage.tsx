// NeuralClaw Desktop — About Page

import Header from '../components/layout/Header';
import { APP_NAME, APP_VERSION, APP_DESCRIPTION } from '../lib/constants';
import { useAppStore } from '../store/appStore';

export default function AboutPage() {
  const { backendVersion } = useAppStore();

  return (
    <>
      <Header title="About" />
      <div className="app-content">
        <div className="page-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 60 }}>
          <div style={{ fontSize: 64, marginBottom: 16 }}>🧠</div>
          <h1 style={{ fontSize: 28, fontWeight: 800, marginBottom: 4 }}>{APP_NAME}</h1>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 24 }}>{APP_DESCRIPTION}</p>

          <div className="summary-grid" style={{ width: '100%', maxWidth: 360 }}>
            <div className="summary-row">
              <span className="summary-label">Desktop</span>
              <span className="summary-value">v{APP_VERSION}</span>
            </div>
            <div className="summary-row">
              <span className="summary-label">Backend</span>
              <span className="summary-value">{backendVersion ? `v${backendVersion}` : 'Not connected'}</span>
            </div>
            <div className="summary-row">
              <span className="summary-label">Shell</span>
              <span className="summary-value">Tauri 2</span>
            </div>
            <div className="summary-row">
              <span className="summary-label">Frontend</span>
              <span className="summary-value">React 19 + TypeScript</span>
            </div>
            <div className="summary-row">
              <span className="summary-label">Engine</span>
              <span className="summary-value">NeuralClaw Cognitive Pipeline</span>
            </div>
          </div>

          <div style={{ marginTop: 32, display: 'flex', gap: 12 }}>
            <button className="btn btn-primary">Check for Updates</button>
            <button className="btn btn-secondary" onClick={() => window.open('https://github.com/placeparks/neuralclaw')}>
              GitHub ↗
            </button>
          </div>

          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 32 }}>
            Built with ❤️ by the NeuralClaw team
          </p>
        </div>
      </div>
    </>
  );
}
