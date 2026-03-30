// NeuralClaw Desktop — Sidecar Process Management
//
// Manages the Python backend sidecar lifecycle: start, stop, health checks.

use std::sync::Mutex;
use tauri::Manager;

#[derive(Default)]
pub struct SidecarState {
    pub running: bool,
    pub port: u16,
}

/// Start the NeuralClaw Python sidecar process.
/// In production, this spawns the bundled binary.
/// In development, it connects to an already-running gateway.
pub async fn start_sidecar_process(app: &tauri::AppHandle) -> Result<(), String> {
    let port: u16 = 8099;

    // Try to connect to existing gateway first (dev mode)
    if check_health(port).await {
        let state = app.state::<Mutex<SidecarState>>();
        let mut s = state.lock().map_err(|e| e.to_string())?;
        s.running = true;
        s.port = port;
        return Ok(());
    }

    // In production, spawn the sidecar binary
    // The sidecar binary is bundled at build time via tauri.conf.json externalBin
    #[cfg(not(debug_assertions))]
    {
        use tauri_plugin_shell::ShellExt;
        let _sidecar = app
            .shell()
            .sidecar("neuralclaw-sidecar")
            .map_err(|e| format!("Failed to create sidecar command: {}", e))?
            .args(["gateway", "--web-port", &port.to_string()])
            .spawn()
            .map_err(|e| format!("Failed to spawn sidecar: {}", e))?;

        // Wait for sidecar to become healthy
        wait_for_health(port, 30).await?;
    }

    let state = app.state::<Mutex<SidecarState>>();
    let mut s = state.lock().map_err(|e| e.to_string())?;
    s.running = true;
    s.port = port;

    Ok(())
}

/// Stop the sidecar process.
pub async fn stop_sidecar_process(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<Mutex<SidecarState>>();
    let mut s = state.lock().map_err(|e| e.to_string())?;
    s.running = false;
    Ok(())
}

/// Check if the sidecar is healthy.
pub async fn check_health(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{}/api/health", port);
    match reqwest::get(&url).await {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

/// Wait for sidecar health endpoint to respond.
async fn wait_for_health(port: u16, timeout_secs: u64) -> Result<(), String> {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed().as_secs() > timeout_secs {
            return Err("Sidecar failed to start within timeout".into());
        }
        if check_health(port).await {
            return Ok(());
        }
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
}
