//! Generic 5 MB chunked uploader used by both:
//!   - [`crate::delivery`] (POSTs `/api/requirements/{id}/delivery/{init|chunk|finalize}`)
//!   - [`crate::commands::submitter::upload_attachment`]
//!     (POSTs `/api/requirements/{id}/upload/{init|chunk/idx|finalize}`)
//!
//! Both backend flows speak the same protocol: init → many chunk PUTs → finalize.
//! The only thing that differs is the URL template, which the caller provides
//! via closures. Progress events are emitted under a caller-chosen event name.
//!
//! Keeping a single implementation means bugs (off-by-one chunk size, missing
//! auth header, mismatched content-type) get fixed once for everyone.

use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::Arc;

use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::config::ConfigState;
use crate::error::{Error, Result};
use crate::http;

pub const CHUNK_SIZE: usize = 5 * 1024 * 1024;

#[derive(Debug, Serialize, Clone)]
pub struct UploadProgress {
    pub req_id: String,
    pub phase: String,  // "init" | "chunk" | "finalize" | "done"
    pub sent: u64,
    pub total: u64,
}

pub struct UploadUrls<F, G, H>
where
    F: Fn() -> String,
    G: Fn(usize, &str) -> String,
    H: Fn(&str) -> String,
{
    pub init: F,
    pub chunk: G,
    pub finalize: H,
}

/// Upload `file_path` to the configured backend, emitting `event_name` progress
/// events tagged with `req_id`. Returns the JSON response from the finalize
/// endpoint (e.g. the created `AttachmentOut` record).
///
/// `init_extras` is merged into the init body before sending — used by callers
/// that need extra fields like `{parent_id, conflict}` for project-drive uploads.
pub async fn upload_file<F, G, H>(
    app: &AppHandle,
    state: &Arc<ConfigState>,
    req_id: &str,
    file_path: &Path,
    filename: &str,
    mime: Option<&str>,
    urls: UploadUrls<F, G, H>,
    event_name: &str,
    init_extras: Option<serde_json::Value>,
) -> Result<serde_json::Value>
where
    F: Fn() -> String,
    G: Fn(usize, &str) -> String,
    H: Fn(&str) -> String,
{
    let size = std::fs::metadata(file_path)?.len();
    let total_chunks = ((size as usize + CHUNK_SIZE - 1) / CHUNK_SIZE).max(1);

    emit(app, event_name, req_id, "init", 0, size);

    let client = http::client(state);

    // init
    let init_url = (urls.init)();
    let mut init_body = serde_json::json!({
        "filename": filename,
        "total_size": size,
        "total_chunks": total_chunks,
        "mime": mime.unwrap_or("application/octet-stream"),
    });
    if let (Some(obj), Some(extras)) = (init_body.as_object_mut(), init_extras.as_ref().and_then(|v| v.as_object())) {
        for (k, v) in extras { obj.insert(k.clone(), v.clone()); }
    }
    let init: serde_json::Value = http::with_auth(client.post(&init_url), state)
        .json(&init_body)
        .send().await?
        .error_for_status()?
        .json().await?;

    let upload_id = init.get("upload_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| Error::Other("init response missing upload_id".into()))?
        .to_string();

    // chunks
    let mut f = File::open(file_path)?;
    let mut sent: u64 = 0;
    for idx in 0..total_chunks {
        let mut buf = vec![0u8; CHUNK_SIZE];
        let n = f.read(&mut buf)?;
        buf.truncate(n);
        let url = (urls.chunk)(idx, &upload_id);
        http::with_auth(client.put(&url), state)
            .header("Content-Type", "application/octet-stream")
            .body(buf)
            .send().await?
            .error_for_status()?;
        sent += n as u64;
        emit(app, event_name, req_id, "chunk", sent, size);
    }

    // finalize
    emit(app, event_name, req_id, "finalize", sent, size);
    let fin_url = (urls.finalize)(&upload_id);
    let final_body: serde_json::Value = http::with_auth(client.post(&fin_url), state)
        .send().await?
        .error_for_status()?
        .json().await?;

    emit(app, event_name, req_id, "done", size, size);
    Ok(final_body)
}

fn emit(app: &AppHandle, event: &str, req_id: &str, phase: &str, sent: u64, total: u64) {
    let _ = app.emit(event, UploadProgress {
        req_id: req_id.to_string(),
        phase: phase.to_string(),
        sent,
        total,
    });
}
