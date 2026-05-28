//! 60s tick poll /api/reminders/due + /api/notifications?status=unread
//! Forwards anything with severity high/urgent to a toast.

use std::time::Duration;

use tauri::{AppHandle, Emitter};
use tauri_plugin_notification::NotificationExt;

use crate::config::ConfigState;
use crate::http;

pub fn spawn(app: AppHandle, state: ConfigState) {
    tauri::async_runtime::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(60));
        loop {
            ticker.tick().await;
            if let Err(e) = poll_reminders(&app, &state).await {
                tracing::warn!("reminder poll err: {e}");
            }
            if let Err(e) = poll_notifications(&app, &state).await {
                tracing::warn!("notification poll err: {e}");
            }
        }
    });
}

async fn poll_reminders(app: &AppHandle, state: &ConfigState) -> anyhow::Result<()> {
    let url = http::url(state, "/api/reminders/due");
    let client = http::client(state);
    let resp = http::with_auth(client.get(&url), state).send().await?;
    if !resp.status().is_success() {
        return Ok(());
    }
    let list: serde_json::Value = resp.json().await?;
    if let Some(arr) = list.as_array() {
        for r in arr {
            let title = r.get("title").and_then(|v| v.as_str()).unwrap_or("DDL").to_string();
            let req_id = r.get("requirement_id").and_then(|v| v.as_str()).map(String::from);
            let code = r.get("requirement_code").and_then(|v| v.as_str()).unwrap_or("");
            let kind = r.get("kind").and_then(|v| v.as_str()).unwrap_or("");
            let mins = r.get("minutes_until_due").and_then(|v| v.as_i64()).unwrap_or(0);
            let body = match kind {
                "overdue" => format!("{code} 已超过截止时间 {} 分钟", mins.abs()),
                "due_now" => format!("{code} 现在到截止时间"),
                _ => format!("{code} 还有 {mins} 分钟到截止时间"),
            };
            let _ = app.notification().builder()
                .title(format!("截止时间：{title}"))
                .body(body)
                .show();
            let _ = app.emit("reminder", serde_json::json!({
                "kind": kind, "title": title, "requirement_id": req_id,
            }));
        }
    }
    Ok(())
}

async fn poll_notifications(app: &AppHandle, state: &ConfigState) -> anyhow::Result<()> {
    let url = http::url(state, "/api/notifications?status=unread");
    let client = http::client(state);
    let resp = http::with_auth(client.get(&url), state).send().await?;
    if !resp.status().is_success() { return Ok(()); }
    let list: serde_json::Value = resp.json().await?;
    if let Some(arr) = list.as_array() {
        for n in arr {
            let severity = n.get("severity").and_then(|v| v.as_str()).unwrap_or("normal");
            if severity == "high" || severity == "urgent" {
                let title = n.get("title").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let body = n.get("body").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let _ = app.notification().builder()
                    .title(title).body(body).show();
            }
            let _ = app.emit("notification", n.clone());
        }
    }
    Ok(())
}
