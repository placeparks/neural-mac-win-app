// NeuralClaw Desktop — IPC Command Handlers
//
// Proxy requests to the NeuralClaw backend:
//  - Dashboard REST API on port 8080
//  - WebChat WebSocket on port 8099

use crate::sidecar;
use std::sync::Mutex;
use tauri::State;

const DASHBOARD_URL: &str = "http://127.0.0.1:8080";

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
    let health = sidecar::check_health(port).await;
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

// ── Chat (via Dashboard /api/message for simple test messages) ──────

#[tauri::command]
pub async fn send_message(message: String) -> Result<String, String> {
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{}/api/message", DASHBOARD_URL))
        .json(&serde_json::json!({ "content": message }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn clear_chat() -> Result<String, String> {
    Ok("{\"ok\":true}".to_string())
}

#[tauri::command]
pub async fn get_chat_history() -> Result<String, String> {
    Ok("[]".to_string())
}

#[tauri::command]
pub async fn update_config(config: serde_json::Value) -> Result<String, String> {
    Ok("{\"ok\":true}".to_string())
}

#[tauri::command]
pub async fn search_memory(query: String) -> Result<String, String> {
    Ok("[]".to_string())
}

#[tauri::command]
pub async fn get_kb_documents() -> Result<String, String> {
    Ok("[]".to_string())
}

#[tauri::command]
pub async fn ingest_kb_document(file_path: String) -> Result<String, String> {
    Ok("{\"ok\":true}".to_string())
}

#[tauri::command]
pub async fn search_kb(query: String) -> Result<String, String> {
    Ok("[]".to_string())
}

#[tauri::command]
pub async fn get_workflows() -> Result<String, String> {
    Ok("[]".to_string())
}

#[tauri::command]
pub async fn create_workflow(workflow: serde_json::Value) -> Result<String, String> {
    Ok("{\"ok\":true}".to_string())
}

#[tauri::command]
pub async fn run_workflow(workflow_id: String) -> Result<String, String> {
    Ok("{\"ok\":true}".to_string())
}
