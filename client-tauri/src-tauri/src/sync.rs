//! Requirement-level + project-drive-level file sync.
//! Mirrors `client/yqgl_tray.py:480-707` but uses reqwest + tokio + sha2.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::anyhow;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter};
use tokio::fs;
use tokio::io::AsyncWriteExt;

use crate::config::ConfigState;
use crate::error::Result;
use crate::http;

#[derive(Debug, Serialize, Deserialize)]
pub struct ManifestFile {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub sha256: Option<String>,
    #[serde(default)]
    pub size: Option<u64>,
    #[serde(default)]
    pub mime: Option<String>,
    pub download_url: String,
    #[serde(default)]
    pub role: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Manifest {
    pub code: String,
    pub project_slug: String,
    pub title: Option<String>,
    pub status: String,
    #[serde(default)]
    pub priority: String,
    pub submitter_nickname: String,
    #[serde(default)]
    pub claimed_by_nickname: Option<String>,
    #[serde(default)]
    pub files: Vec<ManifestFile>,
    #[serde(default)]
    pub workspaces: Vec<serde_json::Value>,
    #[serde(default)]
    pub acceptance_items: Vec<serde_json::Value>,
    #[serde(default)]
    pub task_plans: Vec<serde_json::Value>,
    #[serde(default)]
    pub chat: Vec<serde_json::Value>,
    #[serde(default)]
    pub summary_md: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
pub struct SyncProgress {
    pub req_id: String,
    pub phase: String,
    pub percent: u8,
    pub message: Option<String>,
}

pub async fn sync_requirement(
    app: AppHandle,
    state: Arc<ConfigState>,
    req_id: String,
) -> Result<()> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/sync-manifest"));

    emit_progress(&app, &req_id, "manifest", 5, "正在拉清单");
    let manifest: Manifest = http::with_auth(client.get(&url), &state).send().await?.error_for_status()?.json().await?;

    let cfg = state.read();
    let root = PathBuf::from(&cfg.sync_root)
        .join(&manifest.project_slug)
        .join(&manifest.code);
    fs::create_dir_all(&root).await?;
    let attach_dir = root.join("attachments");
    fs::create_dir_all(&attach_dir).await?;

    // Write metadata files
    let meta = serde_json::json!({
        "code": manifest.code,
        "title": manifest.title,
        "status": manifest.status,
        "priority": manifest.priority,
        "submitter": manifest.submitter_nickname,
        "claimed_by": manifest.claimed_by_nickname,
        "files": manifest.files.iter().map(|f| serde_json::json!({
            "id": f.id,
            "name": f.name,
            "sha256": f.sha256,
            "size": f.size,
        })).collect::<Vec<_>>(),
    });
    fs::write(root.join("metadata.json"), serde_json::to_vec_pretty(&meta)?).await?;
    if let Some(md) = &manifest.summary_md {
        fs::write(
            root.join("requirement.md"),
            format!("# {}\n\n{}\n", manifest.title.clone().unwrap_or_default(), md),
        ).await?;
    }
    if !manifest.workspaces.is_empty() {
        fs::write(root.join("workspace.md"), workspaces_to_md(&manifest.workspaces)).await?;
    }

    // Download each file
    let total = manifest.files.len().max(1);
    for (idx, f) in manifest.files.iter().enumerate() {
        let target = attach_dir.join(&f.name);
        let percent = 10 + (80 * (idx + 1) / total) as u8;

        // Skip if local sha matches
        if let (Some(want), true) = (&f.sha256, target.exists()) {
            if let Ok(local) = fs::read(&target).await {
                let actual = hex::encode(Sha256::digest(&local));
                if &actual == want {
                    emit_progress(&app, &req_id, "skip", percent, &format!("已是最新：{}", f.name));
                    continue;
                }
            }
        }

        emit_progress(&app, &req_id, "download", percent, &format!("下载：{}", f.name));
        let dl_url = if f.download_url.starts_with("http") {
            f.download_url.clone()
        } else {
            http::url(&state, &f.download_url)
        };
        let resp = http::with_auth(client.get(&dl_url), &state).send().await?.error_for_status()?;
        let bytes = resp.bytes().await?;
        let mut file = fs::File::create(&target).await?;
        file.write_all(&bytes).await?;
        file.flush().await?;
    }

    // Ack
    let ack_url = http::url(&state, &format!("/api/requirements/{req_id}/sync-ack"));
    http::with_auth(client.post(&ack_url), &state).send().await?.error_for_status()?;
    emit_progress(&app, &req_id, "done", 100, "完成");

    Ok(())
}

fn workspaces_to_md(ws: &[serde_json::Value]) -> String {
    let mut out = String::from("# 工作区\n\n");
    for w in ws {
        let nick = w.get("nickname").and_then(|v| v.as_str()).unwrap_or("?");
        let phase = w.get("phase").and_then(|v| v.as_str()).unwrap_or("");
        let pct = w.get("progress_percent").and_then(|v| v.as_i64()).unwrap_or(0);
        out.push_str(&format!("## {nick}\n- 阶段：{phase}\n- 进度：{pct}%\n\n"));
    }
    out
}

fn emit_progress(app: &AppHandle, req_id: &str, phase: &str, percent: u8, msg: &str) {
    let _ = app.emit("sync-progress", SyncProgress {
        req_id: req_id.to_string(),
        phase: phase.to_string(),
        percent,
        message: Some(msg.to_string()),
    });
}

/// Sync a project drive (placeholder: full bidirectional + sha256 + conflict handling
/// is in plan §6.5; this initial implementation does single-direction download).
pub async fn sync_drive_download(
    app: AppHandle,
    state: Arc<ConfigState>,
    project_id: String,
) -> Result<()> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/projects/{project_id}/drive/manifest"));
    let manifest: serde_json::Value = http::with_auth(client.get(&url), &state).send().await?.error_for_status()?.json().await?;

    let cfg = state.read();
    let slug = manifest.get("project_slug").and_then(|v| v.as_str()).unwrap_or("unknown");
    let root = PathBuf::from(&cfg.drive_sync_root).join(slug);
    fs::create_dir_all(&root).await?;

    let items = manifest.get("items").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let total = items.len().max(1);
    for (idx, it) in items.iter().enumerate() {
        let kind = it.get("kind").and_then(|v| v.as_str()).unwrap_or("file");
        let path = it.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let abs = root.join(path.trim_start_matches('/'));
        if kind == "folder" {
            fs::create_dir_all(&abs).await?;
            continue;
        }
        let url_field = it.get("download_url").and_then(|v| v.as_str()).unwrap_or("");
        if url_field.is_empty() { continue; }
        if let Some(parent) = abs.parent() { fs::create_dir_all(parent).await?; }

        // sha256 cache check
        let want = it.get("sha256").and_then(|v| v.as_str()).unwrap_or("");
        if abs.exists() && !want.is_empty() {
            if let Ok(local) = fs::read(&abs).await {
                let actual = hex::encode(Sha256::digest(&local));
                if actual == want { continue; }
            }
        }
        let dl = if url_field.starts_with("http") {
            url_field.to_string()
        } else {
            http::url(&state, url_field)
        };
        let bytes = http::with_auth(client.get(&dl), &state).send().await?.error_for_status()?.bytes().await?;
        let mut f = fs::File::create(&abs).await?;
        f.write_all(&bytes).await?;
        f.flush().await?;
        let pct = (90 * (idx + 1) / total) as u8;
        let _ = app.emit("drive-sync-progress", serde_json::json!({
            "project_id": project_id, "phase": "download", "percent": pct,
        }));
    }
    let _ = app.emit("drive-sync-progress", serde_json::json!({
        "project_id": project_id, "phase": "done", "percent": 100u8,
    }));
    Ok(())
}

// Helper kept private to avoid leaking sha2 directly to other modules.
fn _assert_path_is_inside(parent: &Path, child: &Path) -> anyhow::Result<()> {
    if !child.starts_with(parent) {
        return Err(anyhow!("path escapes root"));
    }
    Ok(())
}
