use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Manager, PhysicalPosition, State, WebviewWindow};

const AVATAR_WINDOW_WIDTH: i32 = 300;
const AVATAR_WINDOW_HEIGHT: i32 = 400;
const AVATAR_MARGIN: i32 = 24;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AvatarPosition {
    pub x: i32,
    pub y: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AvatarWindowState {
    pub visible: bool,
    pub anchor: String,
    pub position: AvatarPosition,
    pub emotion: String,
    #[serde(rename = "isSpeaking")]
    pub is_speaking: bool,
    #[serde(rename = "modelPath")]
    pub model_path: String,
    pub scale: f64,
}

impl Default for AvatarWindowState {
    fn default() -> Self {
        Self {
            visible: false,
            anchor: "bottom-right".into(),
            position: AvatarPosition { x: 100, y: 100 },
            emotion: "neutral".into(),
            is_speaking: false,
            model_path: String::new(),
            scale: 1.0,
        }
    }
}

fn avatar_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("avatar")
        .ok_or_else(|| "Avatar window not configured".to_string())
}

fn main_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("main")
        .ok_or_else(|| "Main window not configured".to_string())
}

fn avatar_dimensions(scale: f64) -> (i32, i32) {
    let clamped = scale.clamp(0.5, 2.0);
    let width = ((AVATAR_WINDOW_WIDTH as f64) * clamped).round() as i32;
    let height = ((AVATAR_WINDOW_HEIGHT as f64) * clamped).round() as i32;
    (width.clamp(180, 640), height.clamp(240, 860))
}

fn clamp_position(app: &AppHandle, x: i32, y: i32, scale: f64) -> (i32, i32) {
    let (width, height) = avatar_dimensions(scale);
    if let Ok(Some(monitor)) = app.primary_monitor() {
        let size = monitor.size();
        let pos = monitor.position();
        let max_x = pos.x + size.width as i32 - width;
        let max_y = pos.y + size.height as i32 - height;
        return (x.clamp(pos.x, max_x), y.clamp(pos.y, max_y));
    }
    (x.max(0), y.max(0))
}

fn anchored_position(app: &AppHandle, anchor: &str, scale: f64) -> Result<AvatarPosition, String> {
    let monitor = app
        .primary_monitor()
        .map_err(|err| err.to_string())?
        .ok_or_else(|| "Primary monitor unavailable".to_string())?;
    let size = monitor.size();
    let pos = monitor.position();
    let (width, height) = avatar_dimensions(scale);

    let right = pos.x + size.width as i32 - width - AVATAR_MARGIN;
    let left = pos.x + AVATAR_MARGIN;
    let top = pos.y + AVATAR_MARGIN;
    let bottom = pos.y + size.height as i32 - height - AVATAR_MARGIN;

    let (x, y) = match anchor {
        "bottom-left" => (left, bottom),
        "top-right" => (right, top),
        "top-left" => (left, top),
        "taskbar" => (right, bottom),
        _ => (right, bottom),
    };

    Ok(AvatarPosition { x, y })
}

fn apply_window_state(app: &AppHandle, state: &AvatarWindowState) -> Result<(), String> {
    let window = avatar_window(app)?;
    let (width, height) = avatar_dimensions(state.scale);
    window
        .set_size(tauri::Size::Physical(tauri::PhysicalSize::new(width as u32, height as u32)))
        .map_err(|err| err.to_string())?;
    window
        .set_position(PhysicalPosition::new(state.position.x, state.position.y))
        .map_err(|err| err.to_string())?;
    if state.visible {
        window.show().map_err(|err| err.to_string())?;
    } else {
        window.hide().map_err(|err| err.to_string())?;
    }
    Ok(())
}

fn emit_navigation(window: &WebviewWindow, target_view: Option<&str>) -> Result<(), String> {
    if let Some(view) = target_view {
        let payload = serde_json::to_string(view).map_err(|err| err.to_string())?;
        window
            .eval(&format!(
                "window.dispatchEvent(new CustomEvent('neuralclaw:navigate', {{ detail: {} }}));",
                payload
            ))
            .map_err(|err| err.to_string())?;
    }
    Ok(())
}

pub fn toggle_avatar_window_internal(
    app: &AppHandle,
    avatar_state: &Mutex<AvatarWindowState>,
) -> Result<AvatarWindowState, String> {
    let next_state = {
        let mut state = avatar_state.lock().map_err(|err| err.to_string())?;
        state.visible = !state.visible;
        if state.anchor != "free" {
            state.position = anchored_position(app, &state.anchor, state.scale)?;
        }
        state.clone()
    };
    apply_window_state(app, &next_state)?;
    Ok(next_state)
}

pub fn open_main_window_internal(app: &AppHandle, target_view: Option<String>) -> Result<(), String> {
    let window = main_window(app)?;
    window.show().map_err(|err| err.to_string())?;
    window.set_focus().map_err(|err| err.to_string())?;
    emit_navigation(&window, target_view.as_deref())?;
    Ok(())
}

pub fn hide_avatar_window_internal(
    app: &AppHandle,
    avatar_state: &Mutex<AvatarWindowState>,
) -> Result<AvatarWindowState, String> {
    let next_state = {
        let mut state = avatar_state.lock().map_err(|err| err.to_string())?;
        state.visible = false;
        state.clone()
    };
    apply_window_state(app, &next_state)?;
    Ok(next_state)
}

#[tauri::command]
pub fn get_avatar_state(state: State<'_, Mutex<AvatarWindowState>>) -> Result<AvatarWindowState, String> {
    let state = state.lock().map_err(|err| err.to_string())?;
    Ok(state.clone())
}

#[tauri::command]
pub fn toggle_avatar_window(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
) -> Result<AvatarWindowState, String> {
    toggle_avatar_window_internal(&app, state.inner())
}

#[tauri::command]
pub fn set_avatar_position(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
    x: i32,
    y: i32,
) -> Result<AvatarWindowState, String> {
    let next_state = {
        let mut current = state.lock().map_err(|err| err.to_string())?;
        let (x, y) = clamp_position(&app, x, y, current.scale);
        current.anchor = "free".into();
        current.position = AvatarPosition { x, y };
        current.clone()
    };
    apply_window_state(&app, &next_state)?;
    Ok(next_state)
}

#[tauri::command]
pub fn set_avatar_anchor(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
    anchor: String,
) -> Result<AvatarWindowState, String> {
    if anchor == "taskbar" {
        return anchor_to_taskbar(app, state);
    }

    let position = if anchor == "free" {
        let current = state.lock().map_err(|err| err.to_string())?;
        current.position.clone()
    } else {
        let current = state.lock().map_err(|err| err.to_string())?;
        anchored_position(&app, &anchor, current.scale)?
    };

    let next_state = {
        let mut current = state.lock().map_err(|err| err.to_string())?;
        current.anchor = anchor;
        current.position = position;
        current.clone()
    };
    apply_window_state(&app, &next_state)?;
    Ok(next_state)
}

#[tauri::command]
pub fn anchor_to_taskbar(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
) -> Result<AvatarWindowState, String> {
    let next_state = {
        let mut current = state.lock().map_err(|err| err.to_string())?;
        current.anchor = "taskbar".into();
        current.position = anchored_position(&app, "taskbar", current.scale)?;
        current.clone()
    };
    apply_window_state(&app, &next_state)?;
    Ok(next_state)
}

#[tauri::command]
pub fn update_avatar_settings(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
    scale: Option<f64>,
    model_path: Option<String>,
) -> Result<AvatarWindowState, String> {
    let next_state = {
        let mut current = state.lock().map_err(|err| err.to_string())?;
        if let Some(scale) = scale {
            current.scale = scale.clamp(0.5, 2.0);
            if current.anchor != "free" {
                current.position = anchored_position(&app, &current.anchor, current.scale)?;
            } else {
                let (x, y) = clamp_position(&app, current.position.x, current.position.y, current.scale);
                current.position = AvatarPosition { x, y };
            }
        }
        if let Some(model_path) = model_path {
            current.model_path = model_path;
        }
        current.clone()
    };
    apply_window_state(&app, &next_state)?;
    Ok(next_state)
}

#[tauri::command]
pub fn open_main_window(app: AppHandle, target_view: Option<String>) -> Result<(), String> {
    open_main_window_internal(&app, target_view)
}

#[tauri::command]
pub fn hide_avatar_window(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
) -> Result<AvatarWindowState, String> {
    hide_avatar_window_internal(&app, state.inner())
}

#[tauri::command]
pub fn save_avatar_model(
    app: AppHandle,
    state: State<'_, Mutex<AvatarWindowState>>,
    file_name: String,
    bytes: Vec<u8>,
) -> Result<String, String> {
    let file_name = PathBuf::from(file_name)
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| "Invalid file name".to_string())?
        .to_string();

    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|err| err.to_string())?;
    let avatar_dir = app_data.join("avatars");
    fs::create_dir_all(&avatar_dir).map_err(|err| err.to_string())?;

    let path = avatar_dir.join(file_name);
    fs::write(&path, bytes).map_err(|err| err.to_string())?;

    let path_string = path.to_string_lossy().to_string();
    let mut current = state.lock().map_err(|err| err.to_string())?;
    current.model_path = path_string.clone();
    Ok(path_string)
}
