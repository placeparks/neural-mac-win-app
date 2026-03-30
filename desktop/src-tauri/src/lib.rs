// NeuralClaw Desktop — Tauri Application Library
//
// Registers plugins, IPC commands, and sets up the system tray.

mod commands;
mod sidecar;
mod tray;


#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(std::sync::Mutex::new(sidecar::SidecarState::default()))
        .invoke_handler(tauri::generate_handler![
            commands::get_health,
            commands::send_message,
            commands::get_chat_history,
            commands::clear_chat,
            commands::get_config,
            commands::update_config,
            commands::get_memory_episodes,
            commands::search_memory,
            commands::get_kb_documents,
            commands::ingest_kb_document,
            commands::search_kb,
            commands::get_workflows,
            commands::create_workflow,
            commands::run_workflow,
            commands::get_dashboard_stats,
            commands::start_backend,
            commands::stop_backend,
            commands::get_backend_status,
        ])
        .setup(|app| {
            // Build system tray
            tray::create_tray(app)?;

            // Auto-start sidecar on launch
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match sidecar::start_sidecar_process(&handle).await {
                    Ok(_) => println!("[NeuralClaw] Sidecar started successfully"),
                    Err(e) => eprintln!("[NeuralClaw] Failed to start sidecar: {}", e),
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running NeuralClaw");
}
