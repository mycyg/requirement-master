use tauri::State;

use crate::config::ConfigState;
use crate::error::Result;
use crate::http;

#[tauri::command]
pub async fn list_my(
    state: State<'_, ConfigState>,
    assigned_to_me: Option<bool>,
    mine: Option<bool>,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let mut qs: Vec<String> = vec![];
    if assigned_to_me.unwrap_or(false) { qs.push("assigned_to_me=true".into()); }
    if mine.unwrap_or(false) { qs.push("mine=true".into()); }
    let url = http::url(&state, &format!("/api/requirements?{}", qs.join("&")));
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn list_public_pool(state: State<'_, ConfigState>) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/requirements?status=ready");
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn get_requirement(state: State<'_, ConfigState>, req_id: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}"));
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn claim(state: State<'_, ConfigState>, req_id: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/claim"));
    Ok(http::with_auth(client.post(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn patch_status(state: State<'_, ConfigState>, req_id: String, status: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/status"));
    Ok(http::with_auth(client.patch(&url), &state)
        .json(&serde_json::json!({ "status": status }))
        .send().await?
        .error_for_status()?
        .json().await?)
}
