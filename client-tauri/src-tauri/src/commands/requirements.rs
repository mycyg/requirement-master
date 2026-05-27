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
    let v: serde_json::Value = client.get(&url).send().await?.error_for_status()?.json().await?;
    Ok(v)
}

#[tauri::command]
pub async fn list_public_pool(state: State<'_, ConfigState>) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/requirements?status=ready");
    let v: serde_json::Value = client.get(&url).send().await?.error_for_status()?.json().await?;
    Ok(v)
}

#[tauri::command]
pub async fn get_requirement(state: State<'_, ConfigState>, req_id: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}"));
    let v: serde_json::Value = client.get(&url).send().await?.error_for_status()?.json().await?;
    Ok(v)
}

#[tauri::command]
pub async fn claim(state: State<'_, ConfigState>, req_id: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/claim"));
    let v: serde_json::Value = client.post(&url).send().await?.error_for_status()?.json().await?;
    Ok(v)
}

#[tauri::command]
pub async fn patch_status(state: State<'_, ConfigState>, req_id: String, status: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/status"));
    let v: serde_json::Value = client
        .patch(&url)
        .json(&serde_json::json!({ "status": status }))
        .send().await?
        .error_for_status()?
        .json().await?;
    Ok(v)
}
