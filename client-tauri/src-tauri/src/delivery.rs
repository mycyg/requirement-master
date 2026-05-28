//! Zip a worker's folder and chunk-upload it via the legacy attachment-style API.

use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde::Serialize;
use tauri::{AppHandle, Emitter};
use zip::write::SimpleFileOptions;
use zip::CompressionMethod;

use crate::config::ConfigState;
use crate::error::{Error, Result};
use crate::http;

const CHUNK_SIZE: usize = 5 * 1024 * 1024;
const EXCLUDE: &[&str] = &[".git", "node_modules", ".venv", "__pycache__", ".idea", ".vscode"];

#[derive(Debug, Serialize, Clone)]
pub struct DeliveryProgress {
    pub req_id: String,
    pub phase: String,
    pub sent: u64,
    pub total: u64,
}

pub async fn start_delivery(
    app: AppHandle,
    state: Arc<ConfigState>,
    req_id: String,
    folder: PathBuf,
) -> Result<()> {
    emit(&app, &req_id, "zip", 0, 0);
    let zip_path = std::env::temp_dir().join(format!("yqgl-delivery-{req_id}.zip"));
    let total_files = zip_dir(&folder, &zip_path)?;
    emit(&app, &req_id, "zipped", total_files as u64, total_files as u64);

    let size = std::fs::metadata(&zip_path)?.len();
    let total_chunks = ((size as usize + CHUNK_SIZE - 1) / CHUNK_SIZE).max(1);

    let client = http::client(&state);

    // init
    let init_url = http::url(&state, &format!("/api/requirements/{req_id}/delivery/init"));
    let init: serde_json::Value = http::with_auth(client.post(&init_url), &state)
        .json(&serde_json::json!({
            "filename": format!("delivery-{req_id}.zip"),
            "total_size": size,
            "total_chunks": total_chunks,
            "mime": "application/zip",
        }))
        .send().await?
        .error_for_status()?
        .json().await?;
    let upload_id = init.get("upload_id").and_then(|v| v.as_str())
        .ok_or_else(|| Error::Other("no upload_id".into()))?
        .to_string();

    // upload chunks
    let mut f = File::open(&zip_path)?;
    let mut sent: u64 = 0;
    for idx in 0..total_chunks {
        let mut buf = vec![0u8; CHUNK_SIZE];
        let n = f.read(&mut buf)?;
        buf.truncate(n);
        let url = http::url(&state, &format!("/api/requirements/{req_id}/delivery/chunk/{idx}?upload_id={upload_id}"));
        http::with_auth(client.put(&url), &state)
            .header("Content-Type", "application/octet-stream")
            .body(buf)
            .send().await?
            .error_for_status()?;
        sent += n as u64;
        emit(&app, &req_id, "upload", sent, size);
    }

    let fin_url = http::url(&state, &format!("/api/requirements/{req_id}/delivery/finalize?upload_id={upload_id}"));
    http::with_auth(client.post(&fin_url), &state).send().await?.error_for_status()?;
    emit(&app, &req_id, "doc_pending", size, size);

    let _ = std::fs::remove_file(&zip_path);
    Ok(())
}

fn zip_dir(src: &Path, out: &Path) -> Result<usize> {
    let file = File::create(out)?;
    let mut zw = zip::ZipWriter::new(file);
    let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);

    let mut count = 0usize;
    walk(src, src, &mut zw, &opts, &mut count)?;
    zw.finish()?;
    Ok(count)
}

fn walk(
    base: &Path,
    cur: &Path,
    zw: &mut zip::ZipWriter<File>,
    opts: &SimpleFileOptions,
    count: &mut usize,
) -> Result<()> {
    for entry in std::fs::read_dir(cur)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().to_string();
        if EXCLUDE.iter().any(|e| name == *e) { continue; }
        let path = entry.path();
        let rel = path.strip_prefix(base).unwrap().to_string_lossy().replace('\\', "/");
        let ft = entry.file_type()?;
        if ft.is_dir() {
            zw.add_directory(&rel, *opts)?;
            walk(base, &path, zw, opts, count)?;
        } else if ft.is_file() {
            zw.start_file(&rel, *opts)?;
            let mut f = File::open(&path)?;
            std::io::copy(&mut f, zw)?;
            *count += 1;
        }
    }
    Ok(())
}

fn emit(app: &AppHandle, req_id: &str, phase: &str, sent: u64, total: u64) {
    let _ = app.emit("delivery-progress", DeliveryProgress {
        req_id: req_id.to_string(),
        phase: phase.to_string(),
        sent,
        total,
    });
}
