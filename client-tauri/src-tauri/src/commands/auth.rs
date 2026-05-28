use serde::{Deserialize, Serialize};
use tauri::State;

use crate::config::ConfigState;
use crate::error::{Error, Result};
use crate::http;

#[derive(Debug, Serialize, Deserialize)]
pub struct Identity {
    pub id: String,
    pub nickname: String,
    #[serde(default)]
    pub created: bool,
    #[serde(default)]
    pub is_admin: bool,
}

#[tauri::command]
pub async fn identify(state: State<'_, ConfigState>, nickname: String) -> Result<Identity> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/auth/identify");
    let id: Identity = client
        .post(&url)
        .json(&serde_json::json!({ "nickname": nickname }))
        .send().await?
        .error_for_status()?
        .json().await?;
    Ok(id)
}

#[tauri::command]
pub async fn me(state: State<'_, ConfigState>) -> Result<Option<Identity>> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/auth/me");
    let resp = client.get(&url).send().await?;
    // Distinguish "not logged in" (401) from "broken response" (anything else).
    // Previously `resp.json().await.ok()` swallowed JSON-parse errors and
    // returned None, indistinguishable from "logged out" — which forced
    // App.tsx to re-onboard the user, which in turn revoked the existing
    // server-side device record (one-way data loss).
    if resp.status().as_u16() == 401 {
        return Ok(None);
    }
    if !resp.status().is_success() {
        return Err(Error::Other(format!(
            "/api/auth/me returned {}", resp.status()
        )));
    }
    let id: Identity = resp.json().await
        .map_err(|e| Error::Other(format!("/api/auth/me body parse failed: {e}")))?;
    Ok(Some(id))
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DeviceToken {
    pub token: String,
    pub device_id: String,
}

#[tauri::command]
pub async fn register_device(
    state: State<'_, ConfigState>,
    device_name: String,
) -> Result<DeviceToken> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/client-devices/register");
    let resp = client
        .post(&url)
        .json(&serde_json::json!({ "device_name": device_name, "platform": std::env::consts::OS }))
        .send().await?
        .error_for_status()?
        .json::<serde_json::Value>().await?;

    // Backend returns { device: ClientDeviceOut, client_token: str }.
    let token = resp.get("client_token").and_then(|v| v.as_str())
        .ok_or_else(|| Error::Other("no client_token in response".into()))?
        .to_string();
    let device_id = resp.get("device")
        .and_then(|d| d.get("id"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    // Persist the worker token. NO http::refresh — that would rebuild the
    // reqwest Client and drop the cookie jar from `/api/auth/identify`. The
    // shared client is intentionally long-lived; the token is attached to each
    // request via `http::auth_headers()` which reads from config every call.
    state.write(|cfg| { cfg.client_token = token.clone(); })?;
    Ok(DeviceToken { token, device_id })
}
