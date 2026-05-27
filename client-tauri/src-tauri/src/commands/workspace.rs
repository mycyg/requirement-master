use tauri::State;

use crate::config::ConfigState;
use crate::error::Result;
use crate::http;

#[tauri::command]
pub async fn list_workspaces(state: State<'_, ConfigState>, req_id: String) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/workspaces"));
    Ok(client.get(&url).send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn patch_my_workspace(
    state: State<'_, ConfigState>,
    req_id: String,
    patch: serde_json::Value,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/workspaces/me"));
    Ok(client.patch(&url).json(&patch).send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn add_workspace_item(
    state: State<'_, ConfigState>,
    req_id: String,
    title: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/workspaces/me/items"));
    Ok(client
        .post(&url)
        .json(&serde_json::json!({ "title": title, "status": "todo" }))
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn patch_workspace_item(
    state: State<'_, ConfigState>,
    item_id: String,
    patch: serde_json::Value,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/workspace-items/{item_id}"));
    Ok(client.patch(&url).json(&patch).send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn add_workspace_update(
    state: State<'_, ConfigState>,
    req_id: String,
    body: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/workspaces/me/updates"));
    Ok(client
        .post(&url)
        .json(&serde_json::json!({ "body": body, "kind": "manual" }))
        .send().await?
        .error_for_status()?
        .json().await?)
}
