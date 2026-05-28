use std::path::PathBuf;
use std::sync::Arc;

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
    let state_arc: Arc<ConfigState> = Arc::new(ConfigState(parking_lot::Mutex::new(state.read())));
    delivery::start_delivery(app, state_arc, req_id, PathBuf::from(folder)).await
}
