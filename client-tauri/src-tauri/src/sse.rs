//! SSE long-connections with exponential backoff. Two streams in parallel:
//!  - `/api/push/stream`        — global non-PII (requirement.ready/.updated)
//!  - `/api/push/stream/me`     — cookie-scoped, only this user's notifications
//!
//! Both forward into a single `push-event` Tauri event so the React side
//! doesn't have to care which channel it came from. Earlier code subscribed
//! only to the global topic — combined with the backend's prior fan-out of
//! notifications to `"all"`, every client received every user's
//! notifications. Splitting now means a curl on `/stream` (anyone) only
//! sees the org-wide non-PII feed.

use std::time::Duration;

use futures_util::StreamExt;
use serde::Serialize;
use tauri::{AppHandle, Emitter};
use tokio::sync::oneshot;

use crate::config::ConfigState;
use crate::http;

#[derive(Debug, Serialize, Clone)]
pub struct PushEvent {
    pub event: String,
    pub data: serde_json::Value,
}

pub fn spawn(app: AppHandle, state: ConfigState) -> oneshot::Sender<()> {
    let (stop_tx, mut stop_rx) = oneshot::channel::<()>();

    // We want a single stop signal to cancel both streams. Wrap stop_rx in
    // an Arc<Mutex<>> so both tasks can poll it. Cleaner: have the outer
    // task hold stop_rx and abort the child tasks on stop.
    tauri::async_runtime::spawn(async move {
        let app1 = app.clone();
        let state1 = state.clone();
        let global_handle = tauri::async_runtime::spawn(async move {
            run_stream(&app1, &state1, "/api/push/stream", true).await;
        });
        let app2 = app.clone();
        let state2 = state.clone();
        let user_handle = tauri::async_runtime::spawn(async move {
            run_stream(&app2, &state2, "/api/push/stream/me", false).await;
        });

        // Wait for stop signal or either task ending (which shouldn't
        // happen — they loop forever).
        let _ = stop_rx.try_recv(); // initial flush
        loop {
            if stop_rx.try_recv().is_ok() {
                global_handle.abort();
                user_handle.abort();
                return;
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
    });

    stop_tx
}

/// Connects to `path` and forwards SSE events as Tauri push-event emits.
/// `emit_connection_status` controls whether sse-status events fire (only
/// the global stream does, so we don't double-flash the title bar dot).
async fn run_stream(app: &AppHandle, state: &ConfigState, path: &str, emit_connection_status: bool) {
    let mut backoff_ms: u64 = 1000;
    loop {
        let url = http::url(state, path);
        let client = http::client(state);

        let resp = http::with_auth(client.get(&url), state).send().await;
        match resp {
            Err(e) => {
                tracing::warn!("sse {path} connect failed: {e}");
                if emit_connection_status {
                    let _ = app.emit("sse-status", serde_json::json!({"status": "disconnected"}));
                }
            }
            Ok(r) if !r.status().is_success() => {
                tracing::warn!("sse {path} status {}", r.status());
            }
            Ok(r) => {
                if emit_connection_status {
                    let _ = app.emit("sse-status", serde_json::json!({"status": "connected"}));
                }
                backoff_ms = 1000;
                let mut stream = r.bytes_stream();
                // Buffer raw bytes (not String) — a multi-byte UTF-8 char
                // that straddles two HTTP chunks would have its tail bytes
                // dropped if we tried `str::from_utf8` per chunk. Since
                // `\n` (0x0A) is < 0x80 it never appears inside a multi-
                // byte sequence, so we can safely split on the newline byte
                // and decode each complete line as UTF-8.
                let mut byte_buf: Vec<u8> = Vec::new();
                let mut event_name = String::new();
                let mut data_buf = String::new();

                while let Some(chunk) = stream.next().await {
                    let bytes = match chunk {
                        Ok(b) => b,
                        Err(e) => {
                            tracing::warn!("sse {path} chunk err: {e}");
                            break;
                        }
                    };
                    byte_buf.extend_from_slice(&bytes);
                    while let Some(pos) = byte_buf.iter().position(|&b| b == b'\n') {
                        let line_bytes: Vec<u8> = byte_buf.drain(..=pos).collect();
                        let line_slice = &line_bytes[..line_bytes.len() - 1]; // drop \n
                        let line_str = match std::str::from_utf8(line_slice) {
                            Ok(s) => s.trim_end_matches('\r'),
                            Err(e) => {
                                tracing::warn!("sse {path} invalid utf-8 in line: {e}");
                                continue;
                            }
                        };
                        if line_str.is_empty() {
                            if !event_name.is_empty() {
                                let value: serde_json::Value = serde_json::from_str(&data_buf)
                                    .unwrap_or_else(|_| serde_json::Value::String(data_buf.clone()));
                                let _ = app.emit(
                                    "push-event",
                                    PushEvent { event: event_name.clone(), data: value },
                                );
                            }
                            event_name.clear();
                            data_buf.clear();
                        } else if let Some(rest) = line_str.strip_prefix("event:") {
                            event_name = rest.trim().to_string();
                        } else if let Some(rest) = line_str.strip_prefix("data:") {
                            if !data_buf.is_empty() {
                                data_buf.push('\n');
                            }
                            // Per SSE spec: strip a single leading space, keep the rest as-is.
                            let value = rest.strip_prefix(' ').unwrap_or(rest);
                            data_buf.push_str(value);
                        }
                    }
                }
                if emit_connection_status {
                    let _ = app.emit("sse-status", serde_json::json!({"status": "disconnected"}));
                }
            }
        }

        // Exponential backoff capped at 30s
        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
        backoff_ms = (backoff_ms * 2).min(30_000);
    }
}
