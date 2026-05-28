use std::path::PathBuf;

use tauri::{AppHandle, State};

use crate::config::ConfigState;
use crate::delivery;
use crate::error::Result;

#[tauri::command]
pub async fn start_delivery(
    app: AppHandle,
    state: State<'_, ConfigState>,
    req_id: String,
    folder: String,
) -> Result<()> {
    // Share the live ConfigState (cheap Arc-bump clone) so any token
    // update mid-upload propagates instead of being snapshotted.
    delivery::start_delivery(app, ConfigState::clone(state.inner()), req_id, PathBuf::from(folder)).await
}
