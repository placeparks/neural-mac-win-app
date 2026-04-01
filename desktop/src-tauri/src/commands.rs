// NeuralClaw Desktop — IPC Command Handlers
//
// Proxy requests to the NeuralClaw backend:
//  - Dashboard REST API on port 8080
//  - WebChat WebSocket on port 8099

use crate::sidecar;
use std::sync::Mutex;
use tauri::State;

const DASHBOARD_URL: &str = "http://127.0.0.1:8080";

fn client() -> reqwest::Client {
    reqwest::Client::new()
}

// ── Health & Status ──────────────────────────────────────────────────

#[tauri::command]
pub async fn get_health() -> Result<String, String> {
    let resp = reqwest::get(format!("{}/health", DASHBOARD_URL))
        .await
        .map_err(|e| e.to_string())?;
    let body = resp.text().await.map_err(|e| e.to_string())?;
    Ok(body)
}

#[tauri::command]
pub async fn get_backend_status(
    state: State<'_, Mutex<sidecar::SidecarState>>,
) -> Result<serde_json::Value, String> {
    let (running, port) = {
        let s = state.lock().map_err(|e| e.to_string())?;
        (s.running, s.port)
    };
    let health = sidecar::check_health().await;
    Ok(serde_json::json!({
        "running": running,
        "port": port,
        "healthy": health,
    }))
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
    let resp = reqwest::get(format!("{}/api/stats", DASHBOARD_URL))
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_memory_episodes() -> Result<String, String> {
    let resp = reqwest::get(format!("{}/api/memory", DASHBOARD_URL))
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_config() -> Result<String, String> {
    let resp = reqwest::get(format!("{}/config", DASHBOARD_URL))
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
    let resp = reqwest::get(format!("{}/api/memory", DASHBOARD_URL))
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
    let resp = reqwest::get(format!("{}/api/kb/documents", DASHBOARD_URL))
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

// ── Workflows ────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_workflows() -> Result<String, String> {
    let resp = reqwest::get(format!("{}/api/workflows", DASHBOARD_URL))
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
    let resp = reqwest::get(format!("{}/api/features", DASHBOARD_URL))
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
            let base = endpoint.as_deref().unwrap_or("http://localhost:11434");
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
