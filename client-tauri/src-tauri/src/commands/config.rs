use tauri::State;

use crate::config::{Config, ConfigState};
use crate::error::Result;
use crate::http;

#[tauri::command]
pub fn get_config(state: State<'_, ConfigState>) -> Config {
    state.read()
}

#[tauri::command]
pub fn set_config(state: State<'_, ConfigState>, patch: serde_json::Value) -> Result<Config> {
    let new = state.write(|cfg| {
        if let Some(obj) = patch.as_object() {
            if let Some(v) = obj.get("server_ip").and_then(|v| v.as_str()) { cfg.server_ip = v.into(); cfg.server_url.clear(); }
            if let Some(v) = obj.get("server_port").and_then(|v| v.as_u64()) { cfg.server_port = v as u16; cfg.server_url.clear(); }
            if let Some(v) = obj.get("server_scheme").and_then(|v| v.as_str()) { cfg.server_scheme = v.into(); cfg.server_url.clear(); }
            if let Some(v) = obj.get("server_url").and_then(|v| v.as_str()) { cfg.server_url = v.into(); }
            if let Some(v) = obj.get("nickname").and_then(|v| v.as_str()) { cfg.nickname = v.into(); }
            if let Some(v) = obj.get("cookie_token").and_then(|v| v.as_str()) { cfg.cookie_token = v.into(); }
            if let Some(v) = obj.get("client_token").and_then(|v| v.as_str()) { cfg.client_token = v.into(); }
            if let Some(v) = obj.get("sync_root").and_then(|v| v.as_str()) { cfg.sync_root = v.into(); }
            if let Some(v) = obj.get("drive_sync_root").and_then(|v| v.as_str()) { cfg.drive_sync_root = v.into(); }
            if let Some(v) = obj.get("drive_sync_enabled").and_then(|v| v.as_bool()) { cfg.drive_sync_enabled = v; }
            if let Some(v) = obj.get("drive_sync_mode").and_then(|v| v.as_str()) { cfg.drive_sync_mode = v.into(); }
            if let Some(v) = obj.get("drive_sync_paused").and_then(|v| v.as_bool()) { cfg.drive_sync_paused = v; }
            if let Some(v) = obj.get("availability_status").and_then(|v| v.as_str()) { cfg.availability_status = v.into(); }
            if let Some(v) = obj.get("theme").and_then(|v| v.as_str()) { cfg.theme = v.into(); }
            if let Some(v) = obj.get("reminder_offsets_minutes").and_then(|v| v.as_array()) {
                cfg.reminder_offsets_minutes = v.iter().filter_map(|x| x.as_i64()).collect();
            }
        }
    })?;
    // No http::refresh on cfg patch — the long-lived client picks up the new
    // base_url on the next request, and worker token is per-request injected.
    Ok(new)
}

#[tauri::command]
pub async fn test_server(state: State<'_, ConfigState>) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/health");
    let resp = client.get(&url).send().await?;
    Ok(serde_json::json!({
        "ok": resp.status().is_success(),
        "status": resp.status().as_u16(),
    }))
}
