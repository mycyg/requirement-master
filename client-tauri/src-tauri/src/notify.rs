//! Thin wrapper around tauri-plugin-notification so other modules don't have to
//! import the plugin trait directly.

use tauri::AppHandle;
use tauri_plugin_notification::NotificationExt;

pub fn toast(app: &AppHandle, title: &str, body: &str) {
    let _ = app.notification().builder().title(title).body(body).show();
}
