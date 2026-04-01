// NeuralClaw Desktop - System Tray

use crate::avatar;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    App, Manager,
};

pub fn create_tray(app: &App) -> Result<(), Box<dyn std::error::Error>> {
    let open = MenuItem::with_id(app, "open", "Open NeuralClaw", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&open, &settings, &quit])?;

    TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("NeuralClaw - AI Assistant")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => {
                let _ = avatar::open_main_window_internal(app, None);
            }
            "settings" => {
                let _ = avatar::open_main_window_internal(app, Some("settings".into()));
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let tauri::tray::TrayIconEvent::Click { .. } = event {
                let app = tray.app_handle();
                let avatar_state = app.state::<std::sync::Mutex<avatar::AvatarWindowState>>();
                let _ = avatar::toggle_avatar_window_internal(&app, avatar_state.inner());
            }
        })
        .build(app)?;

    Ok(())
}
