//! Zip a worker's folder and chunk-upload it via the legacy attachment-style API.
//! Sharing the chunked upload protocol with [`crate::upload`] keeps init/chunk/
//! finalize bug fixes in one place.

use std::fs::File;
use std::path::{Path, PathBuf};

use tauri::AppHandle;
use zip::write::SimpleFileOptions;
use zip::CompressionMethod;

use crate::config::ConfigState;
use crate::error::Result;
use crate::http;
use crate::upload::{upload_file, UploadUrls};

const EXCLUDE: &[&str] = &[".git", "node_modules", ".venv", "__pycache__", ".idea", ".vscode"];

pub async fn start_delivery(
    app: AppHandle,
    state: ConfigState,
    req_id: String,
    folder: PathBuf,
) -> Result<()> {
    let zip_path = std::env::temp_dir().join(format!("yqgl-delivery-{req_id}.zip"));
    zip_dir(&folder, &zip_path)?;

    // Hand off to the shared uploader. Delivery uses a slightly different URL
    // template than the regular attachment upload, so we provide our own.
    let urls = UploadUrls {
        init: {
            let s = state.clone();
            let req = req_id.clone();
            move || http::url(&s, &format!("/api/requirements/{req}/delivery/init"))
        },
        chunk: {
            let s = state.clone();
            let req = req_id.clone();
            // Backend route is path-param style:
            // PUT /requirements/{req}/delivery/{upload_id}/chunk/{idx}
            move |idx: usize, upload_id: &str| http::url(
                &s,
                &format!("/api/requirements/{req}/delivery/{upload_id}/chunk/{idx}"),
            )
        },
        finalize: {
            let s = state.clone();
            let req = req_id.clone();
            move |upload_id: &str| http::url(
                &s,
                &format!("/api/requirements/{req}/delivery/{upload_id}/finalize"),
            )
        },
    };

    // Always delete the temp zip — success OR upload failure. Previously
    // the `?` on upload_file aborted before the `remove_file` line, leaking
    // a potentially GB-sized file in the user's temp dir every failed
    // delivery.
    let upload_result = upload_file(
        &app,
        &state,
        &req_id,
        &zip_path,
        &format!("delivery-{req_id}.zip"),
        Some("application/zip"),
        urls,
        "delivery-progress",
        None,
    ).await;
    let _ = std::fs::remove_file(&zip_path);
    upload_result.map(|_| ())
}

fn zip_dir(src: &Path, out: &Path) -> Result<usize> {
    let base = src.canonicalize()?;
    let file = File::create(out)?;
    let mut zw = zip::ZipWriter::new(file);
    let opts = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);

    let mut count = 0usize;
    walk(&base, &base, &mut zw, &opts, &mut count)?;
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
        let ft = entry.file_type()?;
        if ft.is_symlink() {
            tracing::warn!("delivery walk: skipping symlink {}", path.display());
            continue;
        }
        let resolved = match path.canonicalize() {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!("delivery walk: skipping unreadable entry {}: {e}", path.display());
                continue;
            }
        };
        if !resolved.starts_with(base) {
            tracing::warn!("delivery walk: skipping out-of-base entry {}", path.display());
            continue;
        }
        let rel = match resolved.strip_prefix(base) {
            Ok(r) => r.to_string_lossy().replace('\\', "/"),
            Err(_) => {
                tracing::warn!("delivery walk: skipping out-of-base entry {}", path.display());
                continue;
            }
        };
        if ft.is_dir() {
            zw.add_directory(&rel, *opts)?;
            walk(base, &resolved, zw, opts, count)?;
        } else if ft.is_file() {
            zw.start_file(&rel, *opts)?;
            let mut f = File::open(&resolved)?;
            std::io::copy(&mut f, zw)?;
            *count += 1;
        }
    }
    Ok(())
}
