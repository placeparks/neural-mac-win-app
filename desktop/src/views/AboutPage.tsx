// NeuralClaw Desktop — About Page

import { useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import Header from '../components/layout/Header';
import { APP_NAME, APP_VERSION, APP_DESCRIPTION } from '../lib/constants';
import { useAppStore } from '../store/appStore';

export default function AboutPage() {
  const { backendVersion, connectionStatus } = useAppStore();
  const [updateStatus, setUpdateStatus] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const handleCheckUpdates = async () => {
    setChecking(true);
    setUpdateStatus(null);
    try {
      // Use the Tauri updater plugin to check for updates
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      if (update) {
        setUpdateStatus(`Update v${update.version} available! Downloading...`);
        await update.downloadAndInstall();
        setUpdateStatus('Update installed. Restart the app to apply.');
      } else {
        setUpdateStatus('You are on the latest version.');
      }
    } catch (err) {
      setUpdateStatus('Could not check for updates. Try again later.');
    } finally {
      setChecking(false);
    }
  };

  // Try to get backend version via health if not set
  const [fetchedVersion, setFetchedVersion] = useState<string | null>(null);
  if (!backendVersion && !fetchedVersion) {
    invoke<string>('get_health').then(r => {
      try {
        const h = JSON.parse(r);
        if (h.version) setFetchedVersion(h.version);
      } catch { /* */ }
    }).catch(() => {});
  }

  const displayVersion = backendVersion || fetchedVersion;

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
              <span className="summary-value" style={{ color: displayVersion ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                {displayVersion ? `v${displayVersion}` : connectionStatus === 'connected' ? 'Connected' : 'Not connected'}
              </span>
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

          {updateStatus && (
            <div className="info-box" style={{
              marginTop: 16, maxWidth: 360, width: '100%',
              background: updateStatus.includes('latest') ? 'var(--accent-green-muted)' : updateStatus.includes('Could not') ? 'var(--accent-red-muted)' : 'var(--accent-blue-muted, rgba(56,139,253,0.1))',
            }}>
              <span className="info-icon">{updateStatus.includes('latest') ? '✅' : updateStatus.includes('Could not') ? '!' : '🔄'}</span>
              <span>{updateStatus}</span>
            </div>
          )}

          <div style={{ marginTop: 32, display: 'flex', gap: 12 }}>
            <button className="btn btn-primary" onClick={handleCheckUpdates} disabled={checking}>
              {checking ? <><span className="spinner" style={{ width: 14, height: 14 }} /> Checking...</> : 'Check for Updates'}
            </button>
            <button className="btn btn-secondary" onClick={() => window.open('https://github.com/placeparks/neural-mac-win-app')}>
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
