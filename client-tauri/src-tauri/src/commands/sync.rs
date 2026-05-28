use tauri::{AppHandle, State};

use crate::config::ConfigState;
use crate::error::Result;
use crate::sync;

#[tauri::command]
pub async fn trigger_sync(
    app: AppHandle,
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<()> {
    // Clone the shared state — ConfigState::clone is a cheap Arc bump
    // that preserves the underlying Mutex<Config>, so writes elsewhere
    // (set_config, register_device) remain visible to this worker.
    // Explicit ConfigState::clone — (*state).clone() resolves to
    // tauri::State::clone (returns the wrapper, not the inner T).
    sync::sync_requirement(app, ConfigState::clone(state.inner()), req_id).await
}

#[tauri::command]
pub async fn trigger_drive_sync(
    app: AppHandle,
    state: State<'_, ConfigState>,
    project_id: String,
) -> Result<()> {
    sync::sync_drive_download(app, ConfigState::clone(state.inner()), project_id).await
}
