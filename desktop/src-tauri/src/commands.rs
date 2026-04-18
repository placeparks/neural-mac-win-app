// NeuralClaw Desktop — IPC Command Handlers
//
// Proxy requests to the NeuralClaw backend:
//  - Dashboard REST API on port 8080
//  - WebChat WebSocket on port 8099

use crate::sidecar;
use std::sync::Mutex;
use std::time::Duration;
use tauri::State;

const DASHBOARD_URL: &str = "http://127.0.0.1:8080";
const REQUEST_TIMEOUT_SECS: u64 = 30;
const HEALTH_TIMEOUT_SECS: u64 = 5;

fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS))
        .connect_timeout(Duration::from_secs(5))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new())
}

fn fast_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(HEALTH_TIMEOUT_SECS))
        .connect_timeout(Duration::from_secs(2))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new())
}

// ── Health & Status ──────────────────────────────────────────────────

#[tauri::command]
pub async fn get_health() -> Result<String, String> {
    let resp = fast_client().get(format!("{}/health", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    let body = resp.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

#[tauri::command]
pub async fn get_backend_status(
    app: tauri::AppHandle,
    state: State<'_, Mutex<sidecar::SidecarState>>,
) -> Result<serde_json::Value, String> {
    let snapshot = {
        let s = state.lock().map_err(|e| e.to_string())?;
        sidecar::SidecarState {
            running: s.running,
            port: s.port,
            child: None,
            attached_to_existing: s.attached_to_existing,
            restart_count: s.restart_count,
            watchdog_started: s.watchdog_started,
            user_stopped: s.user_stopped,
            start_in_progress: s.start_in_progress,
            startup_deadline: s.startup_deadline,
            last_error: s.last_error.clone(),
            port_owner: s.port_owner.clone(),
            auxiliary_port_owners: s.auxiliary_port_owners.clone(),
            legacy_migration: s.legacy_migration.clone(),
            provider_degraded: s.provider_degraded,
            provider_detail: s.provider_detail.clone(),
        }
    };
    let runtime = sidecar::runtime_status(&app, &snapshot).await;
    serde_json::to_value(runtime).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn start_backend(app: tauri::AppHandle) -> Result<(), String> {
    sidecar::start_sidecar_process(&app).await
}

#[tauri::command]
pub async fn stop_backend(app: tauri::AppHandle) -> Result<(), String> {
    sidecar::stop_sidecar_process(&app).await
}

// ── Dashboard API proxies ────────────────────────────────────────────

#[tauri::command]
pub async fn get_dashboard_stats() -> Result<String, String> {
    let resp = client().get(format!("{}/api/stats", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_memory_episodes() -> Result<String, String> {
    let resp = client().get(format!("{}/api/memory", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_config() -> Result<String, String> {
    let resp = client().get(format!("{}/config", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

// ── Chat ─────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn send_message(message: String) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/message", DASHBOARD_URL))
        .json(&serde_json::json!({ "content": message }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn clear_chat() -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/memory/clear", DASHBOARD_URL))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_chat_history() -> Result<String, String> {
    let resp = client().get(format!("{}/api/memory", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

// ── Config ───────────────────────────────────────────────────────────

#[tauri::command]
pub async fn update_config(config: serde_json::Value) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/config", DASHBOARD_URL))
        .json(&config)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

/// Write wizard config directly to ~/.neuralclaw/config.toml and secrets.
/// This does NOT require the backend to be running — used by the setup wizard
/// so first-launch works even before the sidecar is healthy.
#[tauri::command]
pub async fn save_wizard_config(config: serde_json::Value) -> Result<String, String> {
    let home = dirs::home_dir().ok_or("Cannot resolve home directory")?;
    let nc_dir = home.join(".neuralclaw");
    let data_dir = nc_dir.join("data");
    let log_dir = nc_dir.join("logs");
    let sessions_dir = nc_dir.join("sessions");

    // Ensure directories
    for d in &[&nc_dir, &data_dir, &log_dir, &sessions_dir] {
        std::fs::create_dir_all(d).map_err(|e| format!("mkdir: {}", e))?;
    }

    let config_file = nc_dir.join("config.toml");
    let secrets_file = nc_dir.join(".secrets.toml");

    // Read existing config.toml (may not exist on fresh install)
    let mut existing: toml::Table = if config_file.exists() {
        let raw = std::fs::read_to_string(&config_file).unwrap_or_default();
        raw.parse().unwrap_or_default()
    } else {
        toml::Table::new()
    };

    // Extract secrets from the payload before writing to config
    let mut secrets: toml::Table = if secrets_file.exists() {
        let raw = std::fs::read_to_string(&secrets_file).unwrap_or_default();
        raw.parse().unwrap_or_default()
    } else {
        toml::Table::new()
    };

    if let Some(obj) = config.as_object() {
        // Save provider secrets to .secrets.toml (never in config.toml)
        if let Some(ps) = obj.get("provider_secrets").and_then(|v| v.as_object()) {
            for (provider, key_val) in ps {
                if let Some(key) = key_val.as_str() {
                    if !key.is_empty() {
                        secrets.insert(
                            format!("{}_api_key", provider),
                            toml::Value::String(key.to_string()),
                        );
                    }
                }
            }
        }

        // Merge providers into config
        if let Some(providers) = obj.get("providers").and_then(|v| v.as_object()) {
            let providers_table = existing
                .entry("providers")
                .or_insert_with(|| toml::Value::Table(toml::Table::new()));
            if let Some(tbl) = providers_table.as_table_mut() {
                if let Some(primary) = providers.get("primary").and_then(|v| v.as_str()) {
                    tbl.insert("primary".to_string(), toml::Value::String(primary.to_string()));
                }
                // Write per-provider sections (base_url etc.)
                for (pid, pcfg) in providers {
                    if pid == "primary" { continue; }
                    if let Some(pcfg_obj) = pcfg.as_object() {
                        let section = tbl
                            .entry(pid)
                            .or_insert_with(|| toml::Value::Table(toml::Table::new()));
                        if let Some(section_tbl) = section.as_table_mut() {
                            for (k, v) in pcfg_obj {
                                if let Some(s) = v.as_str() {
                                    section_tbl.insert(k.clone(), toml::Value::String(s.to_string()));
                                }
                            }
                        }
                    }
                }
            }
        }

        // Merge model_roles
        if let Some(roles) = obj.get("model_roles").and_then(|v| v.as_object()) {
            let roles_table = existing
                .entry("model_roles")
                .or_insert_with(|| toml::Value::Table(toml::Table::new()));
            if let Some(tbl) = roles_table.as_table_mut() {
                tbl.insert("enabled".to_string(), toml::Value::Boolean(true));
                for (k, v) in roles {
                    if let Some(s) = v.as_str() {
                        tbl.insert(k.clone(), toml::Value::String(s.to_string()));
                    }
                }
            }
        }

        // Merge features
        if let Some(features) = obj.get("features").and_then(|v| v.as_object()) {
            let feat_table = existing
                .entry("features")
                .or_insert_with(|| toml::Value::Table(toml::Table::new()));
            if let Some(tbl) = feat_table.as_table_mut() {
                for (k, v) in features {
                    if let Some(b) = v.as_bool() {
                        tbl.insert(k.clone(), toml::Value::Boolean(b));
                    }
                }
            }
        }
    }

    // Write config.toml
    let config_str = toml::to_string_pretty(&existing)
        .map_err(|e| format!("toml serialize: {}", e))?;
    std::fs::write(&config_file, config_str)
        .map_err(|e| format!("write config.toml: {}", e))?;

    // Write .secrets.toml
    if !secrets.is_empty() {
        let secrets_str = toml::to_string_pretty(&secrets)
            .map_err(|e| format!("toml serialize secrets: {}", e))?;
        std::fs::write(&secrets_file, secrets_str)
            .map_err(|e| format!("write .secrets.toml: {}", e))?;
    }

    Ok(serde_json::json!({ "ok": true }).to_string())
}

// ── Memory / Search ──────────────────────────────────────────────────

#[tauri::command]
pub async fn search_memory(query: String) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/memory/search", DASHBOARD_URL))
        .json(&serde_json::json!({ "query": query }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

// ── Knowledge Base ───────────────────────────────────────────────────

#[tauri::command]
pub async fn get_kb_documents() -> Result<String, String> {
    let resp = client().get(format!("{}/api/kb/documents", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn ingest_kb_document(file_path: String) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/kb/ingest", DASHBOARD_URL))
        .json(&serde_json::json!({ "file_path": file_path }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn search_kb(query: String) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/kb/search", DASHBOARD_URL))
        .json(&serde_json::json!({ "query": query }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_kb_document(document_id: String) -> Result<String, String> {
    let resp = client()
        .delete(format!("{}/api/kb/documents/{}", DASHBOARD_URL, document_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn ingest_kb_text(
    title: String,
    text: String,
    source: Option<String>,
    mime_type: Option<String>,
    content: Option<String>,
) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/kb/ingest-text", DASHBOARD_URL))
        .json(&serde_json::json!({
            "title": title,
            "text": text,
            "source": source.unwrap_or_default(),
            "mime_type": mime_type.unwrap_or_default(),
            "content": content.unwrap_or_default(),
        }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

// ── Workflows ────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_workflows() -> Result<String, String> {
    let resp = client().get(format!("{}/api/workflows", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn create_workflow(workflow: serde_json::Value) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/workflows", DASHBOARD_URL))
        .json(&workflow)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn run_workflow(workflow_id: String) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/workflows/{}/run", DASHBOARD_URL, workflow_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn pause_workflow(workflow_id: String) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/workflows/{}/pause", DASHBOARD_URL, workflow_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn delete_workflow(workflow_id: String) -> Result<String, String> {
    let resp = client()
        .delete(format!("{}/api/workflows/{}", DASHBOARD_URL, workflow_id))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

// ── Features ─────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_features() -> Result<String, String> {
    let resp = client().get(format!("{}/api/features", DASHBOARD_URL)).send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn set_feature(feature: String, value: bool) -> Result<String, String> {
    let resp = client()
        .post(format!("{}/api/features", DASHBOARD_URL))
        .json(&serde_json::json!({ "feature": feature, "value": value }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

// ── API Key Validation ───────────────────────────────────────────────

#[tauri::command]
pub async fn validate_api_key(provider: String, api_key: String, endpoint: Option<String>) -> Result<String, String> {
    // Validate by making a lightweight API call to the provider
    let client = client();
    let result = match provider.as_str() {
        "openai" => {
            let base = endpoint.as_deref().unwrap_or("https://api.openai.com/v1");
            let resp = client
                .get(format!("{}/models", base))
                .header("Authorization", format!("Bearer {}", api_key))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            resp.status().is_success()
        }
        "anthropic" => {
            let base = endpoint.as_deref().unwrap_or("https://api.anthropic.com");
            let resp = client
                .post(format!("{}/v1/messages", base))
                .header("x-api-key", &api_key)
                .header("anthropic-version", "2023-06-01")
                .json(&serde_json::json!({
                    "model": "claude-haiku-4-5",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}]
                }))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            let status = resp.status().as_u16();
            // 200 = valid, 401 = invalid key, anything else = likely valid key but other issue
            status != 401
        }
        "google" => {
            let base = endpoint.as_deref().unwrap_or("https://generativelanguage.googleapis.com/v1beta");
            let resp = client
                .get(format!("{}/models?key={}", base, api_key))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            resp.status().is_success()
        }
        "xai" => {
            let base = endpoint.as_deref().unwrap_or("https://api.x.ai/v1");
            let resp = client
                .get(format!("{}/models", base))
                .header("Authorization", format!("Bearer {}", api_key))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            resp.status().is_success()
        }
        "venice" | "openrouter" | "mistral" => {
            // OpenAI-compatible APIs
            let base = endpoint.as_deref().unwrap_or(match provider.as_str() {
                "venice" => "https://api.venice.ai/api/v1",
                "openrouter" => "https://openrouter.ai/api/v1",
                "mistral" => "https://api.mistral.ai/v1",
                _ => unreachable!(),
            });
            let resp = client
                .get(format!("{}/models", base))
                .header("Authorization", format!("Bearer {}", api_key))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            resp.status().is_success()
        }
        "local" | "meta" => {
            // Ollama — no key needed, just check connectivity
            let raw = endpoint.as_deref().unwrap_or("http://localhost:11434");
            let base = raw.strip_suffix("/v1").unwrap_or(raw);
            let resp = client
                .get(format!("{}/api/tags", base))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            resp.status().is_success()
        }
        _ => {
            return Err(format!("Unknown provider: {}", provider));
        }
    };

    Ok(serde_json::json!({ "valid": result }).to_string())
}

#[tauri::command]
pub async fn list_provider_models(
    provider: String,
    endpoint: Option<String>,
    api_key: Option<String>,
) -> Result<String, String> {
    let provider_id = provider.trim().to_lowercase();
    let http = client();

    let models = match provider_id.as_str() {
        "local" | "meta" => {
            let raw = endpoint
                .as_deref()
                .unwrap_or("http://localhost:11434/v1");
            let base = raw.strip_suffix("/v1").unwrap_or(raw);
            let resp = http
                .get(format!("{}/api/tags", base))
                .send()
                .await
                .map_err(|e| e.to_string())?;
            let payload: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
            payload
                .get("models")
                .and_then(|value| value.as_array())
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter_map(|item| {
                    let name = item.get("name").and_then(|value| value.as_str())?.trim().to_string();
                    if name.is_empty() {
                        return None;
                    }
                    let size = item
                        .get("details")
                        .and_then(|details| details.get("parameter_size"))
                        .and_then(|value| value.as_str())
                        .unwrap_or("");
                    Some(serde_json::json!({
                        "name": name,
                        "description": if size.is_empty() { "Detected from Ollama" } else { size },
                        "icon": "L"
                    }))
                })
                .collect::<Vec<_>>()
        }
        _ => {
            let base = endpoint.unwrap_or_default();
            if base.trim().is_empty() {
                return Ok(serde_json::json!({ "models": [] }).to_string());
            }
            let mut req = http.get(format!("{}/models", base.trim_end_matches('/')));
            if let Some(secret) = api_key.filter(|value| !value.trim().is_empty()) {
                req = req.header("Authorization", format!("Bearer {}", secret));
            }
            let resp = req.send().await.map_err(|e| e.to_string())?;
            let payload: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
            payload
                .get("data")
                .and_then(|value| value.as_array())
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .filter_map(|item| {
                    let name = item.get("id").and_then(|value| value.as_str())?.trim().to_string();
                    if name.is_empty() {
                        return None;
                    }
                    Some(serde_json::json!({
                        "name": name,
                        "description": "Available from provider",
                        "icon": provider_id.chars().next().unwrap_or('M').to_string(),
                    }))
                })
                .collect::<Vec<_>>()
        }
    };

    Ok(serde_json::json!({ "models": models }).to_string())
}
