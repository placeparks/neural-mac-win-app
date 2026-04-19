// NeuralClaw Desktop - Sidecar Process Management
//
// The desktop runtime owns backend startup through a supervised attach-or-recover
// flow instead of blindly killing processes and respawning.

use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::path::PathBuf;
use std::process::{Child, Command};
#[cfg(not(debug_assertions))]
use std::process::Stdio;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[derive(Clone, Default, serde::Serialize)]
pub struct PortOwnerInfo {
    pub port: u16,
    pub pid: Option<u32>,
    pub process_name: Option<String>,
    pub process_path: Option<String>,
    pub app_owned: bool,
    pub source: String,
}

#[derive(Clone, Default, serde::Serialize)]
pub struct LegacyServiceMigration {
    pub platform: String,
    pub attempted: bool,
    pub found_entries: Vec<String>,
    pub disabled_entries: Vec<String>,
    pub removed_entries: Vec<String>,
    pub notes: Vec<String>,
    pub errors: Vec<String>,
}

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
    pub port_owner: Option<PortOwnerInfo>,
    pub auxiliary_port_owners: Vec<PortOwnerInfo>,
    pub legacy_migration: Option<LegacyServiceMigration>,
    pub provider_degraded: bool,
    pub provider_detail: Option<String>,
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
    pub port_owner: Option<PortOwnerInfo>,
    pub auxiliary_port_owners: Vec<PortOwnerInfo>,
    pub legacy_migration: Option<LegacyServiceMigration>,
    pub provider_degraded: bool,
    pub provider_detail: Option<String>,
}

#[derive(Clone, Debug, Default, serde::Deserialize)]
struct HealthProbeStatus {
    ok: bool,
}

#[derive(Clone, Debug, Default, serde::Deserialize)]
struct DashboardHealthRuntime {
    readiness_phase: Option<String>,
    dashboard_bound: Option<bool>,
    operator_api_ready: Option<bool>,
    adaptive_ready: Option<bool>,
}

#[derive(Clone, Debug, Default, serde::Deserialize)]
struct DashboardHealthPayload {
    status: Option<String>,
    readiness: Option<String>,
    runtime: Option<DashboardHealthRuntime>,
    probes: Option<HashMap<String, HealthProbeStatus>>,
}

const DASHBOARD_PORT: u16 = 8080;
const WEBCHAT_PORT: u16 = 8099;
const FEDERATION_PORT: u16 = 8100;
const HEALTH_TIMEOUT_MS: u64 = 2_500;
const STARTUP_TIMEOUT_SECS: u64 = 60;
const WATCHDOG_INTERVAL_SECS: u64 = 5;
const MAX_RESTARTS_PER_WINDOW: u32 = 5;
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn process_appears_app_owned(name: Option<&str>, path: Option<&str>) -> bool {
    let combined = format!(
        "{} {}",
        name.unwrap_or_default().trim().to_lowercase(),
        path.unwrap_or_default().trim().to_lowercase(),
    );
    combined.contains("neuralclaw-sidecar")
        || combined.contains("neuralclaw")
        || combined.contains("cardify.neuralclaw")
}

#[cfg(target_os = "windows")]
fn configure_windows_utility_command(command: &mut Command) -> &mut Command {
    command.creation_flags(CREATE_NO_WINDOW)
}

#[cfg(target_os = "macos")]
fn current_unix_uid() -> Option<String> {
    #[cfg(unix)]
    {
        let output = Command::new("id").arg("-u").output().ok()?;
        if !output.status.success() {
            return None;
        }
        let uid = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if uid.is_empty() { None } else { Some(uid) }
    }

    #[cfg(not(unix))]
    {
        None
    }
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
fn run_command_capture(program: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(program).args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).to_string())
}

fn inspect_port_owner(port: u16) -> Option<PortOwnerInfo> {
    #[cfg(target_os = "windows")]
    {
        let script = format!(
            "$conn = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; \
             if ($conn) {{ \
               $proc = Get-CimInstance Win32_Process -Filter \"ProcessId = $($conn.OwningProcess)\" -ErrorAction SilentlyContinue; \
               Write-Output \"pid=$($conn.OwningProcess)\"; \
               Write-Output \"name=$($proc.Name)\"; \
               Write-Output \"path=$($proc.ExecutablePath)\"; \
             }}"
        );
        let mut command = Command::new("powershell");
        command.args(["-NoProfile", "-Command", &script]);
        configure_windows_utility_command(&mut command);
        let output = command.output().ok()?;
        if !output.status.success() {
            return None;
        }
        let text = String::from_utf8_lossy(&output.stdout);
        let mut pid = None;
        let mut name = None;
        let mut path = None;
        for line in text.lines() {
            if let Some(value) = line.strip_prefix("pid=") {
                pid = value.trim().parse::<u32>().ok();
            } else if let Some(value) = line.strip_prefix("name=") {
                let trimmed = value.trim();
                if !trimmed.is_empty() {
                    name = Some(trimmed.to_string());
                }
            } else if let Some(value) = line.strip_prefix("path=") {
                let trimmed = value.trim();
                if !trimmed.is_empty() {
                    path = Some(trimmed.to_string());
                }
            }
        }
        if pid.is_none() && name.is_none() && path.is_none() {
            return None;
        }
        return Some(PortOwnerInfo {
            port,
            pid,
            process_name: name.clone(),
            process_path: path.clone(),
            app_owned: process_appears_app_owned(name.as_deref(), path.as_deref()),
            source: "windows-nettcpconnection".into(),
        });
    }

    #[cfg(any(target_os = "macos", target_os = "linux"))]
    {
        let text = run_command_capture(
            "lsof",
            &[
                "-nP",
                &format!("-iTCP:{port}"),
                "-sTCP:LISTEN",
                "-Fpct",
            ],
        )?;
        let mut pid = None;
        let mut name = None;
        for line in text.lines() {
            if let Some(value) = line.strip_prefix('p') {
                pid = value.trim().parse::<u32>().ok();
            } else if let Some(value) = line.strip_prefix('c') {
                let trimmed = value.trim();
                if !trimmed.is_empty() {
                    name = Some(trimmed.to_string());
                }
            }
        }
        let path = pid.and_then(|process_id| {
            run_command_capture("ps", &["-p", &process_id.to_string(), "-o", "command="])
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
        });
        if pid.is_none() && name.is_none() && path.is_none() {
            return None;
        }
        return Some(PortOwnerInfo {
            port,
            pid,
            process_name: name.clone(),
            process_path: path.clone(),
            app_owned: process_appears_app_owned(name.as_deref(), path.as_deref()),
            source: "lsof".into(),
        });
    }

    #[allow(unreachable_code)]
    None
}

fn inspect_auxiliary_ports() -> Vec<PortOwnerInfo> {
    [DASHBOARD_PORT, WEBCHAT_PORT, FEDERATION_PORT]
        .into_iter()
        .filter_map(inspect_port_owner)
        .collect()
}

fn terminate_port_owner(owner: &PortOwnerInfo) -> bool {
    let Some(pid) = owner.pid else {
        return false;
    };
    if !owner.app_owned {
        return false;
    }

    #[cfg(target_os = "windows")]
    {
        let mut command = Command::new("taskkill.exe");
        command.args(["/PID", &pid.to_string(), "/F", "/T"]);
        configure_windows_utility_command(&mut command);
        return command
            .status()
            .map(|status| status.success())
            .unwrap_or(false);
    }

    #[cfg(any(target_os = "macos", target_os = "linux"))]
    {
        let _ = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status();
        std::thread::sleep(Duration::from_millis(500));
        if inspect_port_owner(owner.port)
            .as_ref()
            .and_then(|current| current.pid)
            == Some(pid)
        {
            let _ = Command::new("kill")
                .args(["-KILL", &pid.to_string()])
                .status();
        }
        return inspect_port_owner(owner.port)
            .as_ref()
            .and_then(|current| current.pid)
            != Some(pid);
    }

    #[allow(unreachable_code)]
    false
}

fn migrate_legacy_services() -> LegacyServiceMigration {
    #[cfg(target_os = "macos")]
    {
        let mut report = LegacyServiceMigration {
            platform: "macos".into(),
            ..LegacyServiceMigration::default()
        };
        let Some(home_dir) = dirs::home_dir() else {
            report.notes.push("Home directory unavailable; skipped launch-agent migration.".into());
            return report;
        };
        let Some(uid) = current_unix_uid() else {
            report.notes.push("User id unavailable; skipped launch-agent migration.".into());
            return report;
        };
        let entries = [
            ("com.neuralclaw.agent", home_dir.join("Library/LaunchAgents/com.neuralclaw.agent.plist")),
            ("com.neuralclaw.gateway", home_dir.join("Library/LaunchAgents/com.neuralclaw.gateway.plist")),
        ];
        for (label, path) in entries {
            if !path.exists() {
                continue;
            }
            report.attempted = true;
            report.found_entries.push(path.display().to_string());
            let scoped_label = format!("gui/{uid}/{label}");
            let _ = Command::new("launchctl")
                .args(["bootout", &scoped_label])
                .status();
            let _ = Command::new("launchctl")
                .args(["disable", &scoped_label])
                .status();
            report.disabled_entries.push(label.to_string());
            match fs::remove_file(&path) {
                Ok(_) => report.removed_entries.push(path.display().to_string()),
                Err(error) => report.errors.push(format!("Failed to remove {}: {}", path.display(), error)),
            }
        }
        return report;
    }

    #[cfg(target_os = "linux")]
    {
        let mut report = LegacyServiceMigration {
            platform: "linux".into(),
            ..LegacyServiceMigration::default()
        };
        let Some(home_dir) = dirs::home_dir() else {
            report.notes.push("Home directory unavailable; skipped legacy startup inspection.".into());
            return report;
        };
        let entries = [
            ("neuralclaw-agent.service", home_dir.join(".config/systemd/user/neuralclaw-agent.service")),
            ("neuralclaw-gateway.service", home_dir.join(".config/systemd/user/neuralclaw-gateway.service")),
            ("neuralclaw-agent.desktop", home_dir.join(".config/autostart/neuralclaw-agent.desktop")),
            ("neuralclaw-gateway.desktop", home_dir.join(".config/autostart/neuralclaw-gateway.desktop")),
        ];
        for (label, path) in entries {
            if !path.exists() {
                continue;
            }
            report.attempted = true;
            report.found_entries.push(path.display().to_string());
            if label.ends_with(".service") {
                let _ = Command::new("systemctl")
                    .args(["--user", "disable", "--now", label])
                    .status();
                report.disabled_entries.push(label.to_string());
            }
            match fs::remove_file(&path) {
                Ok(_) => report.removed_entries.push(path.display().to_string()),
                Err(error) => report.errors.push(format!("Failed to remove {}: {}", path.display(), error)),
            }
        }
        if !report.attempted {
            report.notes.push("No known legacy NeuralClaw startup entries found.".into());
        }
        return report;
    }

    #[cfg(target_os = "windows")]
    {
        let mut report = LegacyServiceMigration {
            platform: "windows".into(),
            ..LegacyServiceMigration::default()
        };
        if let Some(startup_dir) = std::env::var("APPDATA")
            .ok()
            .map(PathBuf::from)
            .map(|base| base.join("Microsoft/Windows/Start Menu/Programs/Startup"))
        {
            for entry in [
                "NeuralClaw Agent.lnk",
                "NeuralClaw Gateway.lnk",
                "NeuralClaw Agent.bat",
                "NeuralClaw Gateway.bat",
            ] {
                let path = startup_dir.join(entry);
                if !path.exists() {
                    continue;
                }
                report.attempted = true;
                report.found_entries.push(path.display().to_string());
                match fs::remove_file(&path) {
                    Ok(_) => report.removed_entries.push(path.display().to_string()),
                    Err(error) => report.errors.push(format!("Failed to remove {}: {}", path.display(), error)),
                }
            }
        }
        for task_name in ["NeuralClawAgent", "NeuralClawGateway"] {
            let mut query = Command::new("schtasks");
            query.args(["/Query", "/TN", task_name]);
            configure_windows_utility_command(&mut query);
            let exists = query
                .status()
                .map(|status| status.success())
                .unwrap_or(false);
            if !exists {
                continue;
            }
            report.attempted = true;
            report.found_entries.push(format!("ScheduledTask:{task_name}"));
            let mut delete = Command::new("schtasks");
            delete.args(["/Delete", "/TN", task_name, "/F"]);
            configure_windows_utility_command(&mut delete);
            let _ = delete.status();
            report.disabled_entries.push(task_name.to_string());
        }
        if !report.attempted {
            report.notes.push("No known legacy NeuralClaw startup entries found.".into());
        }
        return report;
    }

    #[allow(unreachable_code)]
    LegacyServiceMigration {
        platform: std::env::consts::OS.to_string(),
        notes: vec!["Legacy service migration is not implemented for this platform.".into()],
        ..LegacyServiceMigration::default()
    }
}

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

fn sidecar_candidate_paths_for_names(
    binary_names: &[String],
    current_exe: Option<PathBuf>,
    resource_dir: Option<PathBuf>,
) -> Vec<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(current_exe) = current_exe {
        if let Some(parent) = current_exe.parent() {
            for binary_name in binary_names {
                candidates.push(parent.join(binary_name));
                candidates.push(parent.join("sidecar").join(binary_name));
            }
        }
    }

    if let Some(resource_dir) = resource_dir {
        for binary_name in binary_names {
            candidates.push(resource_dir.join(binary_name));
            candidates.push(resource_dir.join("sidecar").join(binary_name));
        }
    }

    candidates
}

#[allow(dead_code)]
fn resolve_sidecar_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let binary_names = sidecar_binary_names();
    let candidates = sidecar_candidate_paths_for_names(
        &binary_names,
        std::env::current_exe().ok(),
        app.path().resource_dir().ok(),
    );

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

#[cfg(test)]
mod tests {
    use super::sidecar_candidate_paths_for_names;
    use std::path::PathBuf;

    #[test]
    fn macos_bundle_candidates_include_resources_sidecar_path() {
        let binary_names = vec!["neuralclaw-sidecar-aarch64-apple-darwin".to_string()];
        let current_exe = Some(PathBuf::from(
            "/Applications/NeuralClaw.app/Contents/MacOS/NeuralClaw",
        ));
        let resource_dir = Some(PathBuf::from(
            "/Applications/NeuralClaw.app/Contents/Resources",
        ));

        let candidates =
            sidecar_candidate_paths_for_names(&binary_names, current_exe, resource_dir);

        assert!(candidates.contains(&PathBuf::from(
            "/Applications/NeuralClaw.app/Contents/MacOS/neuralclaw-sidecar-aarch64-apple-darwin",
        )));
        assert!(candidates.contains(&PathBuf::from(
            "/Applications/NeuralClaw.app/Contents/Resources/sidecar/neuralclaw-sidecar-aarch64-apple-darwin",
        )));
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

async fn fetch_health_payload() -> Option<DashboardHealthPayload> {
    let url = format!("http://127.0.0.1:{}/health", DASHBOARD_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_millis(HEALTH_TIMEOUT_MS))
        .build()
        .ok()?;
    let response = client.get(&url).send().await.ok()?;
    if !response.status().is_success() {
        return None;
    }
    response.json::<DashboardHealthPayload>().await.ok()
}

async fn classify_existing_backend() -> Option<(DashboardHealthPayload, Option<PortOwnerInfo>)> {
    let payload = fetch_health_payload().await?;
    let owner = inspect_port_owner(DASHBOARD_PORT);
    Some((payload, owner))
}

enum StartOutcome {
    Spawned(Option<Child>),
    AttachedExisting,
}

async fn acquire_sidecar_runtime(app: &tauri::AppHandle) -> Result<StartOutcome, String> {
    let migration = migrate_legacy_services();
    if let Ok(mut state) = app.state::<Mutex<SidecarState>>().lock() {
        state.legacy_migration = Some(migration.clone());
        state.auxiliary_port_owners = inspect_auxiliary_ports();
    }

    if let Some((payload, owner)) = classify_existing_backend().await {
        let status = payload.status.as_deref().unwrap_or_default();
        let readiness = payload.readiness.as_deref().unwrap_or_default();
        let provider_probe_ok = payload
            .probes
            .as_ref()
            .and_then(|probes| probes.get("primary_provider"))
            .map(|probe| probe.ok);
        if status == "healthy" {
            if let Ok(mut state) = app.state::<Mutex<SidecarState>>().lock() {
                state.running = true;
                state.attached_to_existing = true;
                state.port_owner = owner;
                state.provider_degraded = readiness == "degraded" || provider_probe_ok == Some(false);
                state.provider_detail = if state.provider_degraded {
                    Some("Primary provider readiness is degraded; backend stayed online.".into())
                } else {
                    None
                };
                state.last_error = if migration.attempted {
                    Some(format!(
                        "Migrated legacy {} startup entries before attaching to the running backend",
                        migration.platform
                    ))
                } else {
                    None
                };
            }
            append_desktop_log(app, "Attached to existing healthy NeuralClaw backend");
            return Ok(StartOutcome::AttachedExisting);
        }
    }

    let dashboard_owner = inspect_port_owner(DASHBOARD_PORT);
    if let Some(owner) = dashboard_owner.clone() {
        if owner.app_owned {
            append_desktop_log(
                app,
                &format!(
                    "Recovering app-owned backend conflict on port {} (pid {:?})",
                    owner.port, owner.pid
                ),
            );
            let cleaned = terminate_port_owner(&owner);
            std::thread::sleep(Duration::from_millis(1200));
            let remaining_owner = inspect_port_owner(DASHBOARD_PORT);
            if let Ok(mut state) = app.state::<Mutex<SidecarState>>().lock() {
                state.port_owner = remaining_owner.clone();
                state.auxiliary_port_owners = inspect_auxiliary_ports();
                state.last_error = Some(if cleaned {
                    "Recovered from a legacy NeuralClaw background service before startup".into()
                } else {
                    "Detected a legacy NeuralClaw background service but could not fully stop it".into()
                });
            }
            if let Some(remaining) = remaining_owner {
                return Err(format!(
                    "Port {} is still owned by {}{}",
                    remaining.port,
                    remaining.process_name.unwrap_or_else(|| "a legacy NeuralClaw process".into()),
                    remaining
                        .process_path
                        .as_ref()
                        .map(|path| format!(" ({path})"))
                        .unwrap_or_default(),
                ));
            }
        } else {
            if let Ok(mut state) = app.state::<Mutex<SidecarState>>().lock() {
                state.port_owner = Some(owner.clone());
                state.auxiliary_port_owners = inspect_auxiliary_ports();
                state.last_error = Some(format!(
                    "Port {} is already in use by {}{}",
                    owner.port,
                    owner.process_name.clone().unwrap_or_else(|| "another process".into()),
                    owner
                        .process_path
                        .as_ref()
                        .map(|path| format!(" ({path})"))
                        .unwrap_or_default(),
                ));
            }
            return Err(format!(
                "Port {} is already in use by {}{}",
                owner.port,
                owner.process_name.unwrap_or_else(|| "another process".into()),
                owner
                    .process_path
                    .as_ref()
                    .map(|path| format!(" ({path})"))
                    .unwrap_or_default(),
            ));
        }
    }

    let child = spawn_sidecar(app, WEBCHAT_PORT)?;
    if let Ok(mut state) = app.state::<Mutex<SidecarState>>().lock() {
        state.port_owner = None;
        state.auxiliary_port_owners = inspect_auxiliary_ports();
        state.provider_degraded = false;
        state.provider_detail = None;
    }
    Ok(StartOutcome::Spawned(child))
}

pub async fn start_sidecar_process(app: &tauri::AppHandle) -> Result<(), String> {
    let port: u16 = WEBCHAT_PORT;
    append_desktop_log(app, &format!("start_sidecar_process requested on port {}", port));

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
        if let Some(mut child) = s.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    let start_outcome = match acquire_sidecar_runtime(app).await {
        Ok(outcome) => outcome,
        Err(err) => {
            append_desktop_log(app, &format!("Sidecar supervised start failed: {}", err));
            if let Ok(mut s) = app.state::<Mutex<SidecarState>>().lock() {
                s.start_in_progress = false;
                s.last_error = Some(err.clone());
                s.running = false;
            }
            return Err(err);
        }
    };

    {
        let state = app.state::<Mutex<SidecarState>>();
        let mut s = state.lock().map_err(|e| e.to_string())?;
        match start_outcome {
            StartOutcome::Spawned(child) => {
                s.child = child;
                s.running = true;
                s.attached_to_existing = false;
                s.startup_deadline = Some(Instant::now() + Duration::from_secs(STARTUP_TIMEOUT_SECS));
            }
            StartOutcome::AttachedExisting => {
                s.child = None;
                s.running = true;
                s.attached_to_existing = true;
                s.startup_deadline = None;
            }
        }
        ensure_watchdog(app, &mut s);
    }

    if let Err(e) = wait_for_health(STARTUP_TIMEOUT_SECS).await {
        append_desktop_log(app, &format!("Sidecar health wait failed: {}", e));
    }

    let healthy = check_health().await;
    if let Ok(mut s) = app.state::<Mutex<SidecarState>>().lock() {
        s.start_in_progress = false;
        if healthy {
            s.startup_deadline = None;
            s.running = true;
            if !s.provider_degraded {
                s.last_error = None;
            }
        } else if s.last_error.is_none() {
            s.last_error = Some("Backend did not become healthy before the startup timeout.".into());
        }
    }

    Ok(())
}

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
    s.port_owner = None;
    s.auxiliary_port_owners.clear();
    if let Some(mut child) = s.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(())
}

pub async fn check_health() -> bool {
    fetch_health_payload()
        .await
        .and_then(|payload| payload.status)
        .is_some_and(|status| status == "healthy")
}

pub async fn runtime_status(app: &tauri::AppHandle, snapshot: &SidecarState) -> SidecarRuntimeStatus {
    let health_payload = fetch_health_payload().await;
    let dashboard_bound = health_payload
        .as_ref()
        .and_then(|payload| payload.runtime.as_ref())
        .and_then(|runtime| runtime.dashboard_bound)
        .unwrap_or_else(|| health_payload.is_some());
    let payload_status_healthy = health_payload
        .as_ref()
        .and_then(|payload| payload.status.as_deref())
        .is_some_and(|status| status == "healthy");
    let health_readiness = health_payload
        .as_ref()
        .and_then(|payload| payload.readiness.clone());
    let runtime_readiness_phase = health_payload
        .as_ref()
        .and_then(|payload| payload.runtime.as_ref())
        .and_then(|runtime| runtime.readiness_phase.clone());
    let operator_api_ready = health_payload
        .as_ref()
        .and_then(|payload| payload.runtime.as_ref())
        .and_then(|runtime| runtime.operator_api_ready)
        .unwrap_or_else(|| dashboard_bound && snapshot.running);
    let adaptive_ready = health_payload
        .as_ref()
        .and_then(|payload| payload.runtime.as_ref())
        .and_then(|runtime| runtime.adaptive_ready)
        .unwrap_or(operator_api_ready);
    let provider_probe_ok = health_payload
        .as_ref()
        .and_then(|payload| payload.probes.as_ref())
        .and_then(|probes| probes.get("primary_provider"))
        .map(|probe| probe.ok);
    let provider_degraded = snapshot.provider_degraded
        || health_readiness.as_deref() == Some("degraded")
        || provider_probe_ok == Some(false);
    let start_in_progress = snapshot.start_in_progress && !payload_status_healthy;
    let runtime_ready = snapshot.running && payload_status_healthy && operator_api_ready;
    let port_owner = snapshot.port_owner.clone().or_else(|| inspect_port_owner(DASHBOARD_PORT));
    let auxiliary_port_owners = if snapshot.auxiliary_port_owners.is_empty() {
        inspect_auxiliary_ports()
    } else {
        snapshot.auxiliary_port_owners.clone()
    };

    let process_state = if port_owner.as_ref().is_some_and(|owner| !owner.app_owned) {
        "conflict"
    } else if runtime_ready && provider_degraded {
        "degraded"
    } else if runtime_ready {
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

    let readiness_phase: String = if port_owner.as_ref().is_some_and(|owner| !owner.app_owned) {
        "conflict".into()
    } else if start_in_progress && snapshot.legacy_migration.as_ref().is_some_and(|migration| migration.attempted) {
        "recovering".into()
    } else if provider_degraded {
        "degraded".into()
    } else if runtime_ready {
        "ready".into()
    } else if start_in_progress {
        "spawning".into()
    } else if !snapshot.running {
        "offline".into()
    } else if !dashboard_bound {
        "binding_dashboard".into()
    } else if !operator_api_ready {
        runtime_readiness_phase.unwrap_or_else(|| "warming_operator_surface".into())
    } else {
        "ready".into()
    };

    SidecarRuntimeStatus {
        running: snapshot.running,
        port: snapshot.port,
        healthy: payload_status_healthy,
        attached_to_existing: snapshot.attached_to_existing,
        start_in_progress,
        process_state,
        readiness_phase,
        dashboard_bound,
        operator_api_ready,
        adaptive_ready,
        stale_process_cleanup: snapshot
            .legacy_migration
            .as_ref()
            .is_some_and(|migration| migration.attempted),
        desktop_log_path: desktop_log_path(app).map(|p| p.display().to_string()),
        last_error: snapshot.last_error.clone(),
        port_owner,
        auxiliary_port_owners,
        legacy_migration: snapshot.legacy_migration.clone(),
        provider_degraded,
        provider_detail: snapshot.provider_detail.clone().or_else(|| {
            if provider_degraded {
                Some("Primary provider readiness is degraded; backend stayed online.".into())
            } else {
                None
            }
        }),
    }
}

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

fn ensure_watchdog(app: &tauri::AppHandle, s: &mut SidecarState) {
    if s.watchdog_started {
        return;
    }
    s.watchdog_started = true;
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(WATCHDOG_INTERVAL_SECS)).await;

            let (user_stopped, child_alive, start_in_progress, attached_only) = {
                let state = handle.state::<Mutex<SidecarState>>();
                let mut s = match state.lock() {
                    Ok(g) => g,
                    Err(_) => continue,
                };
                let alive = match s.child.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(_)) => false,
                        Ok(None) => true,
                        Err(_) => true,
                    },
                    None => false,
                };
                (
                    s.user_stopped,
                    alive,
                    s.start_in_progress,
                    s.attached_to_existing && s.child.is_none(),
                )
            };

            if user_stopped || start_in_progress {
                continue;
            }

            if attached_only {
                let healthy = check_health().await;
                if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                    s.running = healthy;
                    if !healthy {
                        s.attached_to_existing = false;
                        s.last_error = Some("Attached backend stopped responding; retrying supervised startup.".into());
                    }
                }
                if healthy {
                    continue;
                }
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
                if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                    s.restart_count = 0;
                    s.running = true;
                    s.attached_to_existing = false;
                    s.startup_deadline = None;
                }
                continue;
            }

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
                    s.running = false;
                    s.start_in_progress = false;
                    s.last_error = Some(format!(
                        "Restart cap reached after {} attempts",
                        MAX_RESTARTS_PER_WINDOW
                    ));
                    false
                } else {
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

            append_desktop_log(&handle, "watchdog detected unhealthy sidecar and is restarting it");
            let attempt = handle
                .state::<Mutex<SidecarState>>()
                .lock()
                .map(|s| s.restart_count)
                .unwrap_or(1);
            let backoff = Duration::from_secs((1u64 << attempt.min(5)).min(30));
            tokio::time::sleep(backoff).await;

            match acquire_sidecar_runtime(&handle).await {
                Ok(StartOutcome::Spawned(child)) => {
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
                            if !s.provider_degraded {
                                s.last_error = None;
                            }
                        }
                    }
                }
                Ok(StartOutcome::AttachedExisting) => {
                    if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                        s.child = None;
                        s.running = true;
                        s.attached_to_existing = true;
                        s.start_in_progress = false;
                        s.startup_deadline = None;
                    }
                }
                Err(error) => {
                    append_desktop_log(&handle, &format!("watchdog supervised restart failed: {}", error));
                    if let Ok(mut s) = handle.state::<Mutex<SidecarState>>().lock() {
                        s.start_in_progress = false;
                        s.last_error = Some(error);
                    }
                }
            }
        }
    });
}
