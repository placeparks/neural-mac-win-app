// NeuralClaw Desktop - Sidecar Process Management
//
// Manages the Python backend sidecar lifecycle: spawn, watchdog, restart, kill.
//
// Key resilience properties:
//   * Child process handle is kept so we can kill on app shutdown.
//   * A watchdog task polls health; if the sidecar dies it is automatically
//     respawned (with backoff and a max-restart cap to avoid crash loops).
//   * Health checks have explicit timeouts so they cannot hang the runtime.
//   * `stop_sidecar_process` actually terminates the child instead of just
//     flipping a flag.

use std::fs::{self, OpenOptions};
use std::path::PathBuf;
#[cfg(not(debug_assertions))]
use std::process::Command;
use std::process::Child;
#[cfg(not(debug_assertions))]
use std::process::Stdio;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;

#[derive(Default)]
pub struct SidecarState {
    pub running: bool,
    pub port: u16,
    pub child: Option<Child>,
    pub attached_to_existing: bool,
    pub restart_count: u32,
    pub watchdog_started: bool,
    pub user_stopped: bool,
    pub start_in_progress: bool,
    pub startup_deadline: Option<Instant>,
    pub last_error: Option<String>,
}

#[derive(Clone, serde::Serialize)]
pub struct SidecarRuntimeStatus {
    pub running: bool,
    pub port: u16,
    pub healthy: bool,
    pub attached_to_existing: bool,
    pub start_in_progress: bool,
    pub process_state: String,
    pub readiness_phase: String,
    pub dashboard_bound: bool,
    pub operator_api_ready: bool,
    pub adaptive_ready: bool,
    pub stale_process_cleanup: bool,
    pub desktop_log_path: Option<String>,
    pub last_error: Option<String>,
}

const DASHBOARD_PORT: u16 = 8080;
const WEBCHAT_PORT: u16 = 8099;
const HEALTH_TIMEOUT_MS: u64 = 2_500;
const STARTUP_TIMEOUT_SECS: u64 = 60;
const WATCHDOG_INTERVAL_SECS: u64 = 5;
const MAX_RESTARTS_PER_WINDOW: u32 = 5;

#[allow(dead_code)]
fn sidecar_binary_names() -> Vec<String> {
    let mut names = Vec::new();
    let base = "neuralclaw-sidecar";

    #[cfg(target_os = "windows")]
    {
        names.push(format!("{base}.exe"));
        if let Some(target) = option_env!("TARGET") {
            names.push(format!("{base}-{target}.exe"));
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        names.push(base.to_string());
        if let Some(target) = option_env!("TARGET") {
            names.push(format!("{base}-{target}"));
        }
    }

    names.sort();
    names.dedup();
    names
}

#[allow(dead_code)]
fn resolve_sidecar_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let binary_names = sidecar_binary_names();
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(parent) = current_exe.parent() {
            for binary_name in &binary_names {
                candidates.push(parent.join(binary_name));
                candidates.push(parent.join("sidecar").join(binary_name));
            }
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        for binary_name in &binary_names {
            candidates.push(resource_dir.join(binary_name));
            candidates.push(resource_dir.join("sidecar").join(binary_name));
        }
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| format!(
            "Bundled sidecar not found. Looked for {}",
            binary_names.join(", ")
        ))
}

fn spawn_sidecar(app: &tauri::AppHandle, port: u16) -> Result<Option<Child>, String> {
    #[cfg(debug_assertions)]
    {
        let _ = app;
        let _ = port;
        // In dev mode the gateway is started by the developer; do not spawn.
        Ok(None)
    }

    #[cfg(not(debug_assertions))]
    {
        let sidecar_path = resolve_sidecar_path(app)?;
        let mut command = Command::new(&sidecar_path);
        command.args(["gateway", "--web-port", &port.to_string()]);
        if let Some(home_dir) = dirs::home_dir() {
            let neuralclaw_home = home_dir.join(".neuralclaw");
            command.current_dir(&home_dir);
            command.env("HOME", &home_dir);
            command.env("USERPROFILE", &home_dir);
            command.env("NEURALCLAW_HOME", &neuralclaw_home);
            command.env("NEURALCLAW_CONFIG_DIR", &neuralclaw_home);
        }
        if let Some(log_path) = desktop_log_path(app) {
            if let Some(parent) = log_path.parent() {
                let _ = fs::create_dir_all(parent);
            }
            if let Ok(log_file) = OpenOptions::new().create(true).append(true).open(&log_path) {
                if let Ok(err_file) = log_file.try_clone() {
                    command.stdout(Stdio::from(log_file));
                    command.stderr(Stdio::from(err_file));
                }
            }
        }

        let child = command.spawn().map_err(|e| {
            format!(
                "Failed to spawn sidecar at {}: {}",
                sidecar_path.display(),
                e
            )
        })?;
        Ok(Some(child))
    }
}

pub fn desktop_log_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path()
        .app_log_dir()
        .ok()
        .or_else(|| app.path().app_data_dir().ok())
        .map(|dir| dir.join("neuralclaw-desktop-runtime.log"))
}

pub fn append_desktop_log(app: &tauri::AppHandle, message: &str) {
    if let Some(path) = desktop_log_path(app) {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
            use std::io::Write;
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            let _ = writeln!(file, "[{}] {}", now, message);
        }
    }
}

pub fn cleanup_stale_sidecars() -> bool {
    #[cfg(debug_assertions)]
    {
        return false;
    }

    #[cfg(all(not(debug_assertions), target_os = "windows"))]
    {
        let mut cleaned = false;
        for binary_name in sidecar_binary_names() {
            let status = Command::new("taskkill.exe")
                .args(["/F", "/T", "/IM", &binary_name])
                .status();
            if let Ok(status) = status {
                if status.success() {
                    cleaned = true;
                    eprintln!(
                        "[NeuralClaw] Cleared stale sidecar processes before restart: {}",
                        binary_name
                    );
                }
            }
        }
        return cleaned;
    }

    #[allow(unreachable_code)]
    false
}

/// Start the NeuralClaw Python sidecar process and the watchdog.
pub async fn start_sidecar_process(app: &tauri::AppHandle) -> Result<(), String> {
    let port: u16 = WEBCHAT_PORT;
    append_desktop_log(app, &format!("start_sidecar_process requested on port {}", port));

    // Reset user_stopped on explicit start.
    {
        let state = app.state::<Mutex<SidecarState>>();
        let mut s = state.lock().map_err(|e| e.to_string())?;
        if s.start_in_progress || (s.running && (s.child.is_some() || s.attached_to_existing)) {
            return Ok(());
        }
        s.start_in_progress = true;
        s.last_error = None;
        s.user_stopped = false;
        s.port = port;
        // Reap any lingering child handle we may still be tracking so the
        // name-based taskkill below doesn't race us.
        if let Some(mut child) = s.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    // Release-build desktop owns the sidecar lifecycle. Always kill stale
    // sidecars and spawn a fresh one so config changes are picked up.
    let stale_cleanup = cleanup_stale_sidecars();
    if stale_cleanup {
        append_desktop_log(app, "Recovered from stale sidecar processes before startup");
        if let Ok(mut s) = app.state::<Mutex<SidecarState>>().lock() {
            s.last_error = Some("Recovered from stale sidecar processes before startup".into());
        }
    }
    // Wait long enough for the old process to fully die and release the port.
    // 500ms was too short — PyInstaller sidecars need time to clean up their
    // temp extraction directory.
    tokio::time::sleep(Duration::from_millis(2500)).await;

    // If something is still on port 8080 after cleanup, kill harder and wait.
    if check_health().await {
        eprintln!("[NeuralClaw] Stale sidecar survived cleanup — retrying kill.");
        cleanup_stale_sidecars();
        tokio::time::sleep(Duration::from_millis(3000)).await;
    }

    let child = match spawn_sidecar(app, port) {
        Ok(child) => child,
        Err(err) => {
            append_desktop_log(app, &format!("Sidecar spawn failed: {}", err));
            if let Ok(mut s) = app.state::<Mutex<SidecarState>>().lock() {
                s.start_in_progress = false;
                s.last_error = Some(err.clone());
            }
            return Err(err);
        }
    };

    {
        let state = app.state::<Mutex<SidecarState>>();
        let mut s = state.lock().map_err(|e| e.to_string())?;
        s.child = child;
        s.port = port;
        s.running = true;
        s.attached_to_existing = false;
        s.startup_deadline = Some(Instant::now() + Duration::from_secs(STARTUP_TIMEOUT_SECS));
        ensure_watchdog(app, &mut s);
    }

    // Wait for health, but do not block app startup forever.
    if let Err(e) = wait_for_health(STARTUP_TIMEOUT_SECS).await {
        append_desktop_log(app, &format!("Sidecar health wait failed: {}", e));
        eprintln!("[NeuralClaw] Sidecar startup health wait failed: {}", e);
        // We still leave the child running; the watchdog will try to recover.
    }

    let healthy = check_health().await;
    if let Ok(mut s) = app.state::<Mutex<SidecarState>>().lock() {
        s.start_in_progress = false;
        if healthy {
            append_desktop_log(app, "Sidecar reported healthy after startup");
            s.startup_deadline = None;
            s.running = true;
            s.last_error = None;
        } else if let Some(err) = s.last_error.clone() {
            append_desktop_log(app, &format!("Sidecar startup left in degraded state: {}", err));
        }
    }

    Ok(())
}

/// Stop the sidecar process. Kills the child and signals the watchdog
/// not to restart.
pub async fn stop_sidecar_process(app: &tauri::AppHandle) -> Result<(), String> {
    append_desktop_log(app, "stop_sidecar_process requested");
    let state = app.state::<Mutex<SidecarState>>();
    let mut s = state.lock().map_err(|e| e.to_string())?;
    s.user_stopped = true;
    s.running = false;
    s.attached_to_existing = false;
    s.start_in_progress = false;
    s.startup_deadline = None;
    s.last_error = None;
    if let Some(mut child) = s.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    drop(s);
    cleanup_stale_sidecars();
    Ok(())
}

/// Check if the sidecar dashboard is reachable. Always uses an explicit
/// timeout so it can never hang the caller.
pub async fn check_health() -> bool {
    let url = format!("http://127.0.0.1:{}/health", DASHBOARD_PORT);
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_millis(HEALTH_TIMEOUT_MS))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    match client.get(&url).send().await {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

pub async fn check_operator_api() -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_millis(HEALTH_TIMEOUT_MS))
        .build()
    {
        Ok(c) => c,
        Err(_) => return false,
    };
    match client
        .get(format!("http://127.0.0.1:{}/api/operator/brief", DASHBOARD_PORT))
        .send()
        .await
    {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    }
}

pub async fn runtime_status(app: &tauri::AppHandle, snapshot: &SidecarState) -> SidecarRuntimeStatus {
    let dashboard_bound = check_health().await;
    let operator_api_ready = if dashboard_bound {
        check_operator_api().await
    } else {
        false
    };
    let runtime_ready = snapshot.running && dashboard_bound && operator_api_ready;
    let start_in_progress = snapshot.start_in_progress && !runtime_ready;
    let process_state = if runtime_ready {
        "running"
    } else if start_in_progress {
        "starting"
    } else if snapshot.running && dashboard_bound {
        "degraded"
    } else if snapshot.running {
        "degraded"
    } else if snapshot.user_stopped {
        "stopped"
    } else {
        "offline"
    }
    .to_string();
    let readiness_phase = if runtime_ready {
        "ready"
    } else if start_in_progress {
        "spawning"
    } else if !snapshot.running {
        "offline"
    } else if !dashboard_bound {
        "binding_dashboard"
    } else if !operator_api_ready {
        "warming_operator_surface"
    } else {
        "ready"
    }
    .to_string();

    SidecarRuntimeStatus {
        running: snapshot.running,
        port: snapshot.port,
        healthy: dashboard_bound,
        attached_to_existing: snapshot.attached_to_existing,
        start_in_progress,
        process_state,
        readiness_phase,
        dashboard_bound,
        operator_api_ready,
        adaptive_ready: operator_api_ready,
        stale_process_cleanup: snapshot
            .last_error
            .as_deref()
            .is_some_and(|msg| msg.contains("stale sidecar processes")),
        desktop_log_path: desktop_log_path(app).map(|p| p.display().to_string()),
        last_error: snapshot.last_error.clone(),
    }
}

/// Wait for sidecar health endpoint to respond, with a hard timeout.
async fn wait_for_health(timeout_secs: u64) -> Result<(), String> {
    let start = std::time::Instant::now();
    loop {
        if start.elapsed().as_secs() > timeout_secs {
            return Err("Sidecar failed to start within timeout".into());
        }
        if check_health().await {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

/// Spawn the watchdog task once. It polls health and respawns the sidecar
/// if it dies (subject to a restart cap to avoid crash loops).
fn ensure_watchdog(app: &tauri::AppHandle, s: &mut SidecarState) {
    if s.watchdog_started {
        return;
    }
    s.watchdog_started = true;
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(WATCHDOG_INTERVAL_SECS)).await;

            // Snapshot state.
            let (user_stopped, child_alive, start_in_progress) = {
                let state = handle.state::<Mutex<SidecarState>>();
                let mut s = match state.lock() {
                    Ok(g) => g,
                    Err(_) => continue,
                };
                let alive = match s.child.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(_status)) => false, // exited
                        Ok(None) => true,           // still running
                        Err(_) => true,
                    },
                    None => false,
                };
                (s.user_stopped, alive, s.start_in_progress)
            };

            if user_stopped {
                continue;
            }

            // Another task (start_sidecar_process or a previous watchdog
            // iteration) is mid-spawn. Do not race with it — if we also
            // spawn here, we will orphan one of the child handles and leak
            // a sidecar process.
            if start_in_progress {
                continue;
            }

            let attached_only = handle
                .state::<Mutex<SidecarState>>()
                .lock()
                .map(|s| s.attached_to_existing && s.child.is_none())
                .unwrap_or(false);

            if attached_only {
                let healthy = check_health().await;
                if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                    s.running = healthy;
                }
                continue;
            }

            let healthy = check_health().await;

            let startup_grace = handle
                .state::<Mutex<SidecarState>>()
                .lock()
                .map(|s| s.startup_deadline.is_some_and(|deadline| Instant::now() < deadline))
                .unwrap_or(false);

            if child_alive && !healthy && startup_grace {
                continue;
            }

            if healthy && child_alive {
                // Healthy window — reset restart counter.
                if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                    s.restart_count = 0;
                    s.running = true;
                    s.attached_to_existing = false;
                    s.startup_deadline = None;
                }
                continue;
            }

            // Either child died or health failed.
            let should_restart = {
                let state = handle.state::<Mutex<SidecarState>>();
                let mut s = match state.lock() {
                    Ok(g) => g,
                    Err(_) => continue,
                };
                if s.user_stopped {
                    s.start_in_progress = false;
                    s.last_error = None;
                    false
                } else if s.restart_count >= MAX_RESTARTS_PER_WINDOW {
                    eprintln!(
                        "[NeuralClaw] Sidecar restart cap reached ({}). Giving up until next user start.",
                        MAX_RESTARTS_PER_WINDOW
                    );
                    s.running = false;
                    s.start_in_progress = false;
                    s.last_error = Some(format!(
                        "Restart cap reached after {} attempts",
                        MAX_RESTARTS_PER_WINDOW
                    ));
                    false
                } else {
                    // Reap any dead child handle.
                    if let Some(mut child) = s.child.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                    s.restart_count += 1;
                    s.running = false;
                    s.attached_to_existing = false;
                    s.start_in_progress = true;
                    s.startup_deadline = None;
                    true
                }
            };

            if !should_restart {
                continue;
            }

            eprintln!("[NeuralClaw] Sidecar unhealthy — restarting (attempt {}).",
                handle.state::<Mutex<SidecarState>>()
                    .lock()
                    .map(|s| s.restart_count)
                    .unwrap_or(0));
            append_desktop_log(&handle, "watchdog detected unhealthy sidecar and is restarting it");

            // Backoff before respawn (exponential, capped).
            let attempt = handle
                .state::<Mutex<SidecarState>>()
                .lock()
                .map(|s| s.restart_count)
                .unwrap_or(1);
            let backoff = Duration::from_secs((1u64 << attempt.min(5)).min(30));
            tokio::time::sleep(backoff).await;

            // Sweep any orphaned PyInstaller children by name. When the
            // bootstrap parent dies its extracted-Python child can survive
            // and hold port 8080, which would prevent our respawn from
            // binding and cascade into another restart.
            cleanup_stale_sidecars();
            tokio::time::sleep(Duration::from_millis(1500)).await;

            match spawn_sidecar(&handle, WEBCHAT_PORT) {
                Ok(child) => {
                    append_desktop_log(&handle, "watchdog respawned sidecar process");
                    if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                        s.child = child;
                        s.running = true;
                        s.attached_to_existing = false;
                        s.startup_deadline = Some(Instant::now() + Duration::from_secs(STARTUP_TIMEOUT_SECS));
                        s.last_error = None;
                    }
                    let _ = wait_for_health(STARTUP_TIMEOUT_SECS).await;
                    let healthy = check_health().await;
                    if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                        s.start_in_progress = false;
                        if healthy {
                            s.running = true;
                            s.startup_deadline = None;
                            s.last_error = None;
                        }
                    }
                }
                Err(e) => {
                    append_desktop_log(&handle, &format!("watchdog respawn failed: {}", e));
                    if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                        s.start_in_progress = false;
                        s.last_error = Some(e.clone());
                    }
                    eprintln!("[NeuralClaw] Watchdog respawn failed: {}", e);
                }
            }
        }
    });
}
