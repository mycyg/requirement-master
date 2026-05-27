use std::sync::Arc;

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
    let s: Arc<ConfigState> = Arc::new(ConfigState(parking_lot::Mutex::new(state.read())));
    sync::sync_requirement(app, s, req_id).await
}

#[tauri::command]
pub async fn trigger_drive_sync(
    app: AppHandle,
    state: State<'_, ConfigState>,
    project_id: String,
) -> Result<()> {
    let s: Arc<ConfigState> = Arc::new(ConfigState(parking_lot::Mutex::new(state.read())));
    sync::sync_drive_download(app, s, project_id).await
}
