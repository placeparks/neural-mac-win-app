// NeuralClaw Desktop — Tauri Application Library
//
// Registers plugins, IPC commands, and sets up the system tray.

mod commands;
mod avatar;
mod chat_sessions;
mod sidecar;
mod store;
mod tray;

use tauri::Manager;


#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            sidecar::append_desktop_log(app, "single-instance activation received");
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(std::sync::Mutex::new(sidecar::SidecarState::default()))
        .manage(std::sync::Mutex::new(avatar::AvatarWindowState::default()))
        .invoke_handler(tauri::generate_handler![
            commands::get_health,
            commands::send_message,
            commands::get_chat_history,
            commands::clear_chat,
            commands::get_config,
            commands::update_config,
            commands::save_wizard_config,
            commands::get_memory_episodes,
            commands::search_memory,
            commands::get_kb_documents,
            commands::ingest_kb_document,
            commands::ingest_kb_text,
            commands::search_kb,
            commands::delete_kb_document,
            commands::get_workflows,
            commands::create_workflow,
            commands::run_workflow,
            commands::pause_workflow,
            commands::delete_workflow,
            commands::get_features,
            commands::set_feature,
            commands::validate_api_key,
            commands::list_provider_models,
            commands::get_dashboard_stats,
            commands::start_backend,
            commands::stop_backend,
            commands::get_backend_status,
            store::store_get,
            store::store_set,
            store::store_delete,
            store::store_clear,
            chat_sessions::get_chat_bootstrap,
            chat_sessions::create_chat_session,
            chat_sessions::create_chat_session_with_metadata,
            chat_sessions::switch_chat_session,
            chat_sessions::rename_chat_session,
            chat_sessions::delete_chat_session,
            chat_sessions::clear_chat_session,
            chat_sessions::update_chat_session_metadata,
            chat_sessions::reset_all_chat_sessions,
            chat_sessions::save_chat_draft,
            chat_sessions::save_chat_message,
            avatar::get_avatar_state,
            avatar::toggle_avatar_window,
            avatar::hide_avatar_window,
            avatar::set_avatar_position,
            avatar::set_avatar_anchor,
            avatar::anchor_to_taskbar,
            avatar::update_avatar_settings,
            avatar::open_main_window,
            avatar::save_avatar_model,
        ])
        .setup(|app| {
            sidecar::append_desktop_log(app.handle(), "desktop app setup started");
            // Build system tray
            tray::create_tray(app)?;

            // Auto-start sidecar on launch
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match sidecar::start_sidecar_process(&handle).await {
                    Ok(_) => {
                        sidecar::append_desktop_log(&handle, "sidecar start task completed");
                        println!("[NeuralClaw] Sidecar started successfully");
                    }
                    Err(e) => {
                        sidecar::append_desktop_log(&handle, &format!("sidecar start task failed: {}", e));
                        eprintln!("[NeuralClaw] Failed to start sidecar: {}", e);
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building NeuralClaw")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                sidecar::append_desktop_log(&app_handle, "desktop app exiting");
                // Kill the sidecar child on app exit so we never leave a
                // zombie Python process behind.
                let handle = app_handle.clone();
                tauri::async_runtime::block_on(async move {
                    let _ = sidecar::stop_sidecar_process(&handle).await;
                });
            }
        });
}
