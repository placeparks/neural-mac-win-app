// NeuralClaw Desktop - Sidecar Process Management
//
// Manages the Python backend sidecar lifecycle: start, stop, health checks.

use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;
use tauri::Manager;

#[derive(Default)]
pub struct SidecarState {
    pub running: bool,
    pub port: u16,
}

const DASHBOARD_PORT: u16 = 8080;
const WEBCHAT_PORT: u16 = 8099;

fn sidecar_binary_name() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "neuralclaw-sidecar.exe"
    }
    #[cfg(not(target_os = "windows"))]
    {
        "neuralclaw-sidecar"
    }
}

fn resolve_sidecar_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let binary_name = sidecar_binary_name();
    let mut candidates = Vec::new();

    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            candidates.push(parent.join(binary_name));
            candidates.push(parent.join("sidecar").join(binary_name));
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join(binary_name));
        candidates.push(resource_dir.join("sidecar").join(binary_name));
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| format!("Bundled sidecar not found. Looked for {}", binary_name))
}

/// Start the NeuralClaw Python sidecar process.
/// In production, this spawns the bundled binary.
/// In development, it connects to an already-running gateway.
pub async fn start_sidecar_process(app: &tauri::AppHandle) -> Result<(), String> {
    let port: u16 = WEBCHAT_PORT;

    if check_health().await {
        let state = app.state::<Mutex<SidecarState>>();
        let mut s = state.lock().map_err(|e| e.to_string())?;
        s.running = true;
        s.port = port;
        return Ok(());
    }

    #[cfg(not(debug_assertions))]
    {
        let sidecar_path = resolve_sidecar_path(app)?;
        let mut command = Command::new(&sidecar_path);
        command.args(["gateway", "--web-port", &port.to_string()]);

        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        command
            .spawn()
            .map_err(|e| format!("Failed to spawn sidecar at {}: {}", sidecar_path.display(), e))?;

        wait_for_health(30).await?;
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
pub async fn check_health() -> bool {
    let url = format!("http://127.0.0.1:{}/health", DASHBOARD_PORT);
    match reqwest::get(&url).await {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

/// Wait for sidecar health endpoint to respond.
async fn wait_for_health(timeout_secs: u64) -> Result<(), String> {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed().as_secs() > timeout_secs {
            return Err("Sidecar failed to start within timeout".into());
        }
        if check_health().await {
            return Ok(());
        }
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
}
