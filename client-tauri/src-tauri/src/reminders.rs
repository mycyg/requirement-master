//! 60s tick poll /api/reminders/due + /api/notifications?status=unread
//! Forwards anything with severity high/urgent to a toast.

use std::time::Duration;

use serde_json::map::Map;
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
    let known = state.read().known_reminders;
    let known_map = known.as_object().cloned().unwrap_or_default();
    let mut new_seen: Vec<(String, serde_json::Value)> = Vec::new();
    if let Some(arr) = list.as_array() {
        for r in arr {
            let reminder_id = r.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let due_at = r.get("due_at").and_then(|v| v.as_str()).unwrap_or("");
            let key = format!("{reminder_id}:{due_at}");
            if known_map.contains_key(&key) {
                continue;
            }
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
            new_seen.push((key, serde_json::json!(chrono::Utc::now().to_rfc3339())));
        }
    }
    if !new_seen.is_empty() {
        state.write(|cfg| {
            let mut map: Map<String, serde_json::Value> = cfg.known_reminders.as_object().cloned().unwrap_or_default();
            for (key, value) in new_seen {
                map.insert(key, value);
            }
            prune_seen_map(&mut map, 500);
            cfg.known_reminders = serde_json::Value::Object(map);
        })?;
    }
    Ok(())
}

async fn poll_notifications(app: &AppHandle, state: &ConfigState) -> anyhow::Result<()> {
    let url = http::url(state, "/api/notifications?status=unread");
    let client = http::client(state);
    let resp = http::with_auth(client.get(&url), state).send().await?;
    if !resp.status().is_success() { return Ok(()); }
    let list: serde_json::Value = resp.json().await?;
    let known = state.read().known_notifications;
    let known_map = known.as_object().cloned().unwrap_or_default();
    let mut new_seen: Vec<(String, serde_json::Value)> = Vec::new();
    if let Some(arr) = list.as_array() {
        for n in arr {
            let notification_id = n.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let updated_at = n.get("updated_at").and_then(|v| v.as_str()).unwrap_or("");
            let key = format!("{notification_id}:{updated_at}");
            if known_map.contains_key(&key) {
                continue;
            }
            let severity = n.get("severity").and_then(|v| v.as_str()).unwrap_or("normal");
            if severity == "high" || severity == "urgent" {
                let title = n.get("title").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let body = n.get("body").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let _ = app.notification().builder()
                    .title(title).body(body).show();
            }
            let _ = app.emit("notification", n.clone());
            if !notification_id.is_empty() {
                new_seen.push((key, serde_json::json!(chrono::Utc::now().to_rfc3339())));
            }
        }
    }
    if !new_seen.is_empty() {
        state.write(|cfg| {
            let mut map: Map<String, serde_json::Value> = cfg.known_notifications.as_object().cloned().unwrap_or_default();
            for (key, value) in new_seen {
                map.insert(key, value);
            }
            prune_seen_map(&mut map, 1000);
            cfg.known_notifications = serde_json::Value::Object(map);
        })?;
    }
    Ok(())
}

fn prune_seen_map(map: &mut Map<String, serde_json::Value>, max_entries: usize) {
    if map.len() <= max_entries {
        return;
    }
    let mut items: Vec<(String, String)> = map
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap_or("").to_string()))
        .collect();
    items.sort_by(|a, b| a.1.cmp(&b.1));
    for (key, _) in items.into_iter().take(map.len().saturating_sub(max_entries)) {
        map.remove(&key);
    }
}
