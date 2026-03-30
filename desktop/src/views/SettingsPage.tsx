// NeuralClaw Desktop — Settings Page

import { useState } from 'react';
import Header from '../components/layout/Header';

const SECTIONS = ['General', 'Provider', 'Models', 'Channels', 'Memory', 'Security', 'Features', 'Advanced', 'About'];

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState('General');

  return (
    <>
      <Header title="Settings" />
      <div className="settings-layout" style={{ flex: 1, overflow: 'hidden' }}>
        <nav className="settings-nav">
          {SECTIONS.map((s) => (
            <button
              key={s}
              className={`settings-nav-item ${activeSection === s ? 'active' : ''}`}
              onClick={() => setActiveSection(s)}
            >
              {s}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {activeSection === 'General' && (
            <div className="settings-section">
              <h2>General</h2>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Bot Name</div>
                  <div className="settings-row-desc">The name your AI assistant responds to</div>
                </div>
                <input className="input-field" style={{ width: 200 }} defaultValue="NeuralClaw" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Start on Login</div>
                  <div className="settings-row-desc">Launch NeuralClaw when you log in</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Biometric Lock</div>
                  <div className="settings-row-desc">Require biometric auth to access</div>
                </div>
                <button className="toggle on" />
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Auto-Update</div>
                  <div className="settings-row-desc">Automatically download and install updates</div>
                </div>
                <button className="toggle on" />
              </div>
            </div>
          )}

          {activeSection === 'Provider' && (
            <div className="settings-section">
              <h2>AI Provider</h2>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="input-group" style={{ marginBottom: 16 }}>
                  <label className="input-label">Primary Provider</label>
                  <select className="input-field">
                    <option>Venice</option>
                    <option>OpenAI</option>
                    <option>Anthropic</option>
                    <option>OpenRouter</option>
                    <option>Local (Ollama)</option>
                  </select>
                </div>
                <div className="input-group" style={{ marginBottom: 16 }}>
                  <label className="input-label">API Key</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input className="input-field input-mono" type="password" defaultValue="●●●●●●●●●●" style={{ flex: 1 }} />
                    <button className="btn btn-secondary btn-sm">Change</button>
                  </div>
                </div>
                <div className="input-group">
                  <label className="input-label">Base URL</label>
                  <input className="input-field input-mono" defaultValue="https://api.venice.ai/api/v1" />
                </div>
                <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="status-dot online" />
                  <span style={{ fontSize: 13, color: 'var(--accent-green)' }}>Connected</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-secondary">Test Connection</button>
                <button className="btn btn-primary">Save</button>
              </div>
            </div>
          )}

          {activeSection === 'Channels' && (
            <div className="settings-section">
              <h2>Messaging Channels</h2>
              <div className="card" style={{ marginBottom: 12 }}>
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>✈️</span>
                    <span className="card-title">Telegram</span>
                  </div>
                  <span className="badge badge-green">● Running</span>
                </div>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>Bot: @NeuralClawBot</p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn btn-secondary btn-sm">Configure</button>
                  <button className="btn btn-danger btn-sm">Stop</button>
                </div>
              </div>
              <div className="card">
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>💬</span>
                    <span className="card-title">Discord</span>
                  </div>
                  <span className="badge badge-red">○ Not configured</span>
                </div>
                <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }}>Setup Discord Bot →</button>
              </div>
              <button className="btn btn-secondary" style={{ marginTop: 16 }}>+ Add Channel</button>
            </div>
          )}

          {!['General', 'Provider', 'Channels'].includes(activeSection) && (
            <div className="settings-section">
              <h2>{activeSection}</h2>
              <div className="empty-state">
                <span className="empty-icon">⚙️</span>
                <h3>{activeSection} Settings</h3>
                <p>Configure {activeSection.toLowerCase()} options when the backend is running.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
