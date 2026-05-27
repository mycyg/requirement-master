mod commands;
mod config;
mod deep_link;
mod delivery;
mod error;
mod http;
mod notify;
mod reminders;
mod sse;
mod sync;
mod tray;
mod window;

use std::sync::Arc;

use tauri::Manager;
use tauri_plugin_deep_link::DeepLinkExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::try_from_default_env()
            .unwrap_or_else(|_| "info".into()))
        .init();

    let cfg_state = config::ConfigState::from_disk();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            // Bring main window to front when a second instance is launched.
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
            // Treat extra args as deep-link URLs if matching.
            for a in &args {
                if a.starts_with("yqgl://") {
                    deep_link::handle(app, a);
                }
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_deep_link::init())
        .manage(cfg_state)
        .setup(|app| {
            let handle = app.handle().clone();
            window::decorate(&handle);
            if let Err(e) = tray::install(&handle) {
                tracing::warn!("tray install failed: {e}");
            }

            // Background workers
            let state: tauri::State<config::ConfigState> = handle.state();
            let state_arc: Arc<config::ConfigState> = Arc::new(config::ConfigState(
                parking_lot::Mutex::new(state.read()),
            ));
            let _sse_stop = sse::spawn(handle.clone(), state_arc.clone());
            // Note: keep handle alive for the lifetime of the app.
            Box::leak(Box::new(_sse_stop));
            reminders::spawn(handle.clone(), state_arc.clone());

            // Deep-link plugin → emit navigate
            let h = handle.clone();
            app.deep_link().on_open_url(move |event| {
                for u in event.urls() {
                    deep_link::handle(&h, u.as_str());
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::auth::identify,
            commands::auth::me,
            commands::auth::register_device,
            commands::requirements::list_my,
            commands::requirements::list_public_pool,
            commands::requirements::get_requirement,
            commands::requirements::claim,
            commands::requirements::patch_status,
            commands::workspace::list_workspaces,
            commands::workspace::patch_my_workspace,
            commands::workspace::add_workspace_item,
            commands::workspace::patch_workspace_item,
            commands::workspace::add_workspace_update,
            commands::delivery::start_delivery,
            commands::sync::trigger_sync,
            commands::sync::trigger_drive_sync,
            commands::config::get_config,
            commands::config::set_config,
            commands::config::test_server,
            commands::shell::open_folder,
        ])
        .run(tauri::generate_context!())
        .expect("error while running yqgl client");
}
