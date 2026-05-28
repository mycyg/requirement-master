mod commands;
mod config;
mod deep_link;
mod delivery;
mod error;
mod http;
mod notify;
mod reminders;
mod sse;
mod spec_watch;
mod sync;
mod tray;
mod upload;
mod window;

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

            // Background workers — share the SAME ConfigState as commands
            // (cheap Arc-bump clone). Previously this built a separate
            // ConfigState from a snapshot, so writes via `set_config` /
            // `register_device` were invisible to SSE/reminders until app
            // restart — auth headers stayed empty, notifications silently
            // dropped, drive sync pause toggle did nothing.
            let state: tauri::State<config::ConfigState> = handle.state();
            let shared = config::ConfigState::clone(state.inner());
            let _sse_stop = sse::spawn(handle.clone(), shared.clone());
            // Note: keep handle alive for the lifetime of the app.
            Box::leak(Box::new(_sse_stop));
            reminders::spawn(handle.clone(), shared);

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
            commands::submitter::list_my_projects,
            commands::submitter::list_users,
            commands::submitter::create_requirement,
            commands::submitter::patch_planning,
            commands::submitter::patch_schedule,
            commands::submitter::put_assignees,
            commands::submitter::submit_requirement,
            commands::submitter::accept_requirement,
            commands::submitter::request_revision,
            commands::submitter::list_attachments,
            commands::submitter::upload_attachment,
            commands::submitter::download_delivery,
            commands::submitter::start_spec_watcher,
            commands::submitter::stop_spec_watcher,
            commands::submitter::open_spec_folder,
            commands::submitter::list_drive_root,
            commands::submitter::upload_drive_item,
            commands::submitter::finalize_and_submit,
            commands::submitter::delete_requirement,
            commands::submitter::set_user_admin,
            commands::submitter::delete_user,
            commands::submitter::create_project,
            commands::submitter::delete_project,
            commands::submitter::chat_messages,
            commands::submitter::post_chat_answer,
            commands::submitter::auto_process,
            commands::submitter::update_tray_unread,
        ])
        .run(tauri::generate_context!())
        .expect("error while running yqgl client");
}
