// NeuralClaw Desktop — Lock View

import { useAppStore } from '../store/appStore';

export default function LockView() {
  const { setLocked } = useAppStore();

  const handleUnlock = () => {
    // In production, this would invoke Tauri biometric auth
    // For now, unlock directly
    setLocked(false);
  };

  return (
    <div className="lock-screen">
      <div className="lock-icon">🔐</div>
      <h1 className="lock-title">NeuralClaw</h1>
      <p className="lock-subtitle">Authenticate to unlock</p>

      <button className="btn btn-primary btn-lg" onClick={handleUnlock} style={{ marginTop: 20 }}>
        🔐 Unlock with Biometrics
      </button>

      <button
        className="btn btn-ghost btn-sm"
        style={{ position: 'absolute', bottom: 20, right: 20 }}
        onClick={() => window.close()}
      >
        ⏻ Quit
      </button>
    </div>
  );
}
