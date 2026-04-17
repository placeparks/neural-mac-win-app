use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use tauri::Manager;

fn store_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let base = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("app_data_dir: {}", e))?;
    Ok(base.join("desktop-store.json"))
}

fn read_store(app: &tauri::AppHandle) -> Result<BTreeMap<String, serde_json::Value>, String> {
    let path = store_path(app)?;
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read store: {}", e))?;
    serde_json::from_str(&raw).map_err(|e| format!("parse store: {}", e))
}

fn write_store(app: &tauri::AppHandle, store: &BTreeMap<String, serde_json::Value>) -> Result<(), String> {
    let path = store_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir store dir: {}", e))?;
    }
    let payload = serde_json::to_string_pretty(store).map_err(|e| format!("serialize store: {}", e))?;
    fs::write(path, payload).map_err(|e| format!("write store: {}", e))
}

#[tauri::command]
pub fn store_get(app: tauri::AppHandle, key: String) -> Result<serde_json::Value, String> {
    let store = read_store(&app)?;
    Ok(store.get(&key).cloned().unwrap_or(serde_json::Value::Null))
}

#[tauri::command]
pub fn store_set(app: tauri::AppHandle, key: String, value: serde_json::Value) -> Result<(), String> {
    let mut store = read_store(&app)?;
    store.insert(key, value);
    write_store(&app, &store)
}

#[tauri::command]
pub fn store_delete(app: tauri::AppHandle, key: String) -> Result<(), String> {
    let mut store = read_store(&app)?;
    store.remove(&key);
    write_store(&app, &store)
}

#[tauri::command]
pub fn store_clear(app: tauri::AppHandle) -> Result<(), String> {
    write_store(&app, &BTreeMap::new())
}
