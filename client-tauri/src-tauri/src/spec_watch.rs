//! Watch `{sync_root}/{project_slug}/{code}/spec/` per-requirement so the
//! submitter can drop spec files into a folder and have them auto-uploaded
//! as attachments. Append-only — local deletions never delete remote
//! attachments (too easy to misfire when the user clears the folder).
//!
//! Dedup is SHA256-based: before uploading we list existing attachments on
//! the server and skip any with matching sha256. This handles re-saves of
//! the same file (notify often fires multiple events) and resumes after
//! crash without re-uploading.

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

use notify::{RecursiveMode, Watcher};
use notify_debouncer_full::{new_debouncer, DebounceEventResult, Debouncer, FileIdMap};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use sha2::{Digest, Sha256};
use tauri::AppHandle;
use tracing::{info, warn};

use crate::config::ConfigState;
use crate::error::{Error, Result};
use crate::http;
use crate::upload::{upload_file, UploadUrls};

type DebouncerHandle = Debouncer<notify::RecommendedWatcher, FileIdMap>;

static WATCHERS: Lazy<Mutex<HashMap<String, DebouncerHandle>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

pub fn spec_folder(state: &ConfigState, project_slug: &str, code: &str) -> PathBuf {
    let sync_root = state.read().sync_root.clone();
    PathBuf::from(sync_root).join(project_slug).join(code).join("spec")
}

pub async fn start(
    app: AppHandle,
    state: ConfigState,
    req_id: String,
) -> Result<PathBuf> {
    // Look up project_slug + code so we know what folder to watch.
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}"));
    let meta: serde_json::Value = http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?;
    let slug = meta.get("project_slug").and_then(|v| v.as_str())
        .ok_or_else(|| Error::Other("requirement missing project_slug".into()))?
        .to_string();
    let code = meta.get("code").and_then(|v| v.as_str())
        .ok_or_else(|| Error::Other("requirement missing code".into()))?
        .to_string();

    let folder = spec_folder(&state, &slug, &code);
    std::fs::create_dir_all(&folder)?;

    // Already watching? Stop the old one first so we don't double-fire.
    stop_blocking(&req_id);

    let folder_for_handler = folder.clone();
    let app_for_handler = app.clone();
    let state_for_handler = state.clone();
    let req_for_handler = req_id.clone();

    let mut debouncer = new_debouncer(
        Duration::from_millis(1500),
        None,
        move |result: DebounceEventResult| {
            let events = match result {
                Ok(es) => es,
                Err(errs) => { warn!("spec_watch debounce error: {errs:?}"); return; }
            };
            // De-dupe paths inside this batch — multiple kinds of events can
            // fire for the same file (modify+chunk-write etc.).
            let mut paths: Vec<PathBuf> = events.into_iter()
                .flat_map(|e| e.event.paths.into_iter())
                .filter(|p| p.is_file())
                .filter(|p| p.starts_with(&folder_for_handler))
                .collect();
            paths.sort();
            paths.dedup();

            // Fire off the upload work on tauri's async runtime so we don't
            // block the notify thread (which would lose subsequent events).
            let app = app_for_handler.clone();
            let state = state_for_handler.clone();
            let req = req_for_handler.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = process_changes(&app, &state, &req, paths).await {
                    warn!("spec_watch upload failed for {req}: {e}");
                }
            });
        },
    ).map_err(|e| Error::Other(format!("notify init: {e}")))?;

    debouncer.watcher()
        .watch(&folder, RecursiveMode::NonRecursive)
        .map_err(|e| Error::Other(format!("notify watch: {e}")))?;

    WATCHERS.lock().insert(req_id.clone(), debouncer);
    info!("spec_watch started for {req_id} -> {}", folder.display());
    Ok(folder)
}

fn stop_blocking(req_id: &str) {
    if let Some(d) = WATCHERS.lock().remove(req_id) {
        // Dropping the debouncer stops the underlying watcher cleanly.
        drop(d);
    }
}

pub fn stop(req_id: &str) {
    stop_blocking(req_id);
}

/// Called when files change in the watched folder. For each path:
///   1. Compute SHA256.
///   2. Skip if backend already has an attachment with this SHA.
///   3. Otherwise upload via the shared chunk uploader.
async fn process_changes(
    app: &AppHandle,
    state: &ConfigState,
    req_id: &str,
    paths: Vec<PathBuf>,
) -> Result<()> {
    // 1. Pull existing attachment SHAs once for the whole batch.
    let client = http::client(state);
    let url = http::url(state, &format!("/api/requirements/{req_id}/attachments"));
    let existing: serde_json::Value = http::with_auth(client.get(&url), state)
        .send().await?.error_for_status()?.json().await?;
    let known_shas: std::collections::HashSet<String> = existing.as_array()
        .map(|a| a.iter()
            .filter_map(|v| v.get("sha256").and_then(|s| s.as_str()).map(String::from))
            .collect())
        .unwrap_or_default();

    for path in paths {
        let sha = sha256_of(&path)?;
        if known_shas.contains(&sha) {
            info!("spec_watch skipping (sha matches): {}", path.display());
            continue;
        }
        let filename = path.file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| "drop.bin".to_string());
        let mime = mime_guess::from_path(&path).first_or_octet_stream().essence_str().to_string();

        let req_for_urls = req_id.to_string();
        let urls = UploadUrls {
            init: {
                let s = state.clone();
                let req = req_for_urls.clone();
                move || http::url(&s, &format!("/api/requirements/{req}/upload/init"))
            },
            chunk: {
                let s = state.clone();
                let req = req_for_urls.clone();
                move |idx: usize, upload_id: &str| http::url(
                    &s,
                    &format!("/api/requirements/{req}/upload/{upload_id}/chunk/{idx}"),
                )
            },
            finalize: {
                let s = state.clone();
                let req = req_for_urls.clone();
                move |upload_id: &str| http::url(
                    &s,
                    &format!("/api/requirements/{req}/upload/{upload_id}/finalize"),
                )
            },
        };

        match upload_file(app, state, req_id, &path, &filename, Some(&mime), urls, "upload-progress", None).await {
            Ok(_) => info!("spec_watch uploaded {}", path.display()),
            Err(e) => warn!("spec_watch upload failed for {}: {e}", path.display()),
        }
    }
    Ok(())
}

fn sha256_of(path: &std::path::Path) -> Result<String> {
    use std::io::Read;
    let mut f = std::fs::File::open(path)?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 { break; }
        h.update(&buf[..n]);
    }
    Ok(hex::encode(h.finalize()))
}
