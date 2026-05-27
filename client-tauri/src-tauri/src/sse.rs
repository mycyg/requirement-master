//! SSE long-connection with exponential backoff. Forwards every event to the
//! frontend as a single `push-event` payload `{ event: string, data: any }`.

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

pub fn spawn(app: AppHandle, state: std::sync::Arc<ConfigState>) -> oneshot::Sender<()> {
    let (stop_tx, mut stop_rx) = oneshot::channel::<()>();

    tokio::spawn(async move {
        let mut backoff_ms: u64 = 1000;
        loop {
            // Allow caller-side abort.
            if stop_rx.try_recv().is_ok() {
                break;
            }

            let url = http::url(&state, "/api/push/stream");
            let client = http::client(&state);

            let resp = client.get(&url).send().await;
            match resp {
                Err(e) => {
                    tracing::warn!("sse connect failed: {e}");
                    let _ = app.emit("sse-status", serde_json::json!({"status": "disconnected"}));
                }
                Ok(r) if !r.status().is_success() => {
                    tracing::warn!("sse status {}", r.status());
                }
                Ok(r) => {
                    let _ = app.emit("sse-status", serde_json::json!({"status": "connected"}));
                    backoff_ms = 1000;
                    let mut stream = r.bytes_stream();
                    let mut buf = String::new();
                    let mut event_name = String::new();
                    let mut data_buf = String::new();

                    while let Some(chunk) = stream.next().await {
                        if stop_rx.try_recv().is_ok() {
                            return;
                        }
                        let bytes = match chunk {
                            Ok(b) => b,
                            Err(e) => {
                                tracing::warn!("sse chunk err: {e}");
                                break;
                            }
                        };
                        if let Ok(piece) = std::str::from_utf8(&bytes) {
                            buf.push_str(piece);
                        }
                        while let Some(nl) = buf.find('\n') {
                            let line = buf[..nl].to_string();
                            buf.drain(..=nl);
                            let line = line.trim_end_matches('\r');
                            if line.is_empty() {
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
                            } else if let Some(rest) = line.strip_prefix("event:") {
                                event_name = rest.trim().to_string();
                            } else if let Some(rest) = line.strip_prefix("data:") {
                                if !data_buf.is_empty() {
                                    data_buf.push('\n');
                                }
                                data_buf.push_str(rest.trim());
                            }
                        }
                    }
                    let _ = app.emit("sse-status", serde_json::json!({"status": "disconnected"}));
                }
            }

            // Exponential backoff capped at 30s
            tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
            backoff_ms = (backoff_ms * 2).min(30_000);
        }
    });

    stop_tx
}
