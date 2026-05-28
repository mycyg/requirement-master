//! Requirement-level + project-drive-level file sync.
//! Mirrors `client/yqgl_tray.py:480-707` but uses reqwest + tokio + sha2.

use std::path::{Component, Path, PathBuf};

use anyhow::anyhow;
use futures_util::StreamExt;
use reqwest::Url;
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
    state: ConfigState,
    req_id: String,
) -> Result<()> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/sync-manifest"));

    emit_progress(&app, &req_id, "manifest", 5, "正在拉清单");
    let manifest: Manifest = http::with_auth(client.get(&url), &state).send().await?.error_for_status()?.json().await?;

    let cfg = state.read();
    let root = PathBuf::from(&cfg.sync_root)
        .join(safe_component(&manifest.project_slug, "project")?)
        .join(safe_component(&manifest.code, "requirement")?);
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
        let safe_name = safe_component(&f.name, "attachment")?;
        let target = attach_dir.join(&safe_name);
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

        emit_progress(&app, &req_id, "download", percent, &format!("下载：{}", safe_name));
        let dl_url = resolve_server_url(&state, &f.download_url)?;
        // Stream the body chunk-by-chunk — `resp.bytes().await?` buffers
        // the entire file in memory and would OOM on multi-GB attachments.
        let resp = http::with_auth(client.get(&dl_url), &state).send().await?.error_for_status()?;
        let mut stream = resp.bytes_stream();
        let tmp = target.with_extension(format!("{}.download", upload_safe_suffix(&f.id)));
        ensure_parent_inside_root(&attach_dir, &tmp).await?;
        let mut file = fs::File::create(&tmp).await?;
        let mut downloaded = Sha256::new();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk?;
            downloaded.update(&chunk);
            file.write_all(&chunk).await?;
        }
        file.flush().await?;
        if let Some(want) = &f.sha256 {
            let actual = hex::encode(downloaded.finalize());
            if &actual != want {
                let _ = fs::remove_file(&tmp).await;
                return Err(anyhow!("sha256 mismatch for {}", safe_name).into());
            }
        }
        if target.exists() {
            fs::remove_file(&target).await?;
        }
        fs::rename(&tmp, &target).await?;
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
    state: ConfigState,
    project_id: String,
) -> Result<()> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/projects/{project_id}/drive/manifest"));
    let manifest: serde_json::Value = http::with_auth(client.get(&url), &state).send().await?.error_for_status()?.json().await?;

    let cfg = state.read();
    let slug = manifest.get("project_slug").and_then(|v| v.as_str()).unwrap_or("unknown");
    let root = PathBuf::from(&cfg.drive_sync_root).join(safe_component(slug, "project")?);
    fs::create_dir_all(&root).await?;

    let items = manifest.get("items").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let total = items.len().max(1);
    for (idx, it) in items.iter().enumerate() {
        let kind = it.get("kind").and_then(|v| v.as_str()).unwrap_or("file");
        let path = it.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let rel = safe_relative_path(path)?;
        let abs = root.join(rel);
        if kind == "folder" {
            ensure_dir_inside_root(&root, &abs).await?;
            fs::create_dir_all(&abs).await?;
            ensure_dir_inside_root(&root, &abs).await?;
            continue;
        }
        let url_field = it.get("download_url").and_then(|v| v.as_str()).unwrap_or("");
        if url_field.is_empty() { continue; }

        // sha256 cache check
        let want = it.get("sha256").and_then(|v| v.as_str()).unwrap_or("");
        if abs.exists() && !want.is_empty() {
            if let Ok(local) = fs::read(&abs).await {
                let actual = hex::encode(Sha256::digest(&local));
                if actual == want { continue; }
            }
        }
        let dl = resolve_server_url(&state, url_field)?;
        // Stream chunks instead of buffering — see sync_requirement for context.
        let resp = http::with_auth(client.get(&dl), &state).send().await?.error_for_status()?;
        let mut stream = resp.bytes_stream();
        let item_id = it.get("id").and_then(|v| v.as_str()).unwrap_or("item");
        let tmp = abs.with_extension(format!("{}.download", upload_safe_suffix(item_id)));
        ensure_parent_inside_root(&root, &tmp).await?;
        let mut f = fs::File::create(&tmp).await?;
        let mut downloaded = Sha256::new();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk?;
            downloaded.update(&chunk);
            f.write_all(&chunk).await?;
        }
        f.flush().await?;
        if !want.is_empty() {
            let actual = hex::encode(downloaded.finalize());
            if actual != want {
                let _ = fs::remove_file(&tmp).await;
                return Err(anyhow!("sha256 mismatch for drive item {item_id}").into());
            }
        }
        if abs.exists() {
            fs::remove_file(&abs).await?;
        }
        fs::rename(&tmp, &abs).await?;
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

fn resolve_server_url(state: &ConfigState, raw: &str) -> anyhow::Result<String> {
    let base = Url::parse(&http::base_url(state))?;
    let target = if raw.starts_with("http://") || raw.starts_with("https://") {
        Url::parse(raw)?
    } else {
        base.join(raw)?
    };
    if target.scheme() != base.scheme()
        || target.host_str() != base.host_str()
        || target.port_or_known_default() != base.port_or_known_default()
    {
        return Err(anyhow!("refusing off-server download url: {raw}"));
    }
    Ok(target.to_string())
}

pub(crate) async fn ensure_parent_inside_root(root: &Path, target: &Path) -> anyhow::Result<()> {
    fs::create_dir_all(root).await?;
    let root_canon = fs::canonicalize(root).await?;
    let parent = target.parent().ok_or_else(|| anyhow!("path has no parent"))?;
    let rel_parent = parent.strip_prefix(root).map_err(|_| anyhow!("path escapes sync root"))?;
    let mut checked = root_canon.clone();
    for comp in rel_parent.components() {
        match comp {
            Component::Normal(part) => {
                let next = checked.join(part);
                if fs::try_exists(&next).await.unwrap_or(false) {
                    let resolved = fs::canonicalize(&next).await?;
                    if !resolved.starts_with(&root_canon) {
                        return Err(anyhow!("path escapes sync root"));
                    }
                    checked = resolved;
                } else {
                    fs::create_dir_all(&next).await?;
                    let resolved = fs::canonicalize(&next).await?;
                    if !resolved.starts_with(&root_canon) {
                        return Err(anyhow!("path escapes sync root"));
                    }
                    checked = resolved;
                }
            }
            _ => return Err(anyhow!("path escapes sync root")),
        }
    }
    let parent_canon = fs::canonicalize(parent).await?;
    if !parent_canon.starts_with(&root_canon) {
        return Err(anyhow!("path escapes sync root"));
    }
    Ok(())
}

pub(crate) async fn ensure_dir_inside_root(root: &Path, target: &Path) -> anyhow::Result<()> {
    fs::create_dir_all(root).await?;
    let root_canon = fs::canonicalize(root).await?;
    if fs::try_exists(target).await.unwrap_or(false) {
        let target_canon = fs::canonicalize(target).await?;
        if !target_canon.starts_with(&root_canon) {
            return Err(anyhow!("path escapes sync root"));
        }
        return Ok(());
    }
    ensure_parent_inside_root(root, target).await
}

pub(crate) fn safe_component(raw: &str, fallback: &str) -> anyhow::Result<String> {
    let cleaned = raw.trim();
    if cleaned.chars().any(|c| matches!(c, '/' | '\\' | ':')) {
        return Err(anyhow!("unsafe path component: {raw}"));
    }
    let mut comps = Path::new(cleaned).components();
    match (comps.next(), comps.next()) {
        (Some(Component::Normal(name)), None) => {
            let s = name.to_string_lossy().trim().to_string();
            if s.is_empty() || s == "." || s == ".." {
                Err(anyhow!("unsafe path component: {raw}"))
            } else {
                Ok(s)
            }
        }
        (None, None) if !fallback.is_empty() => Ok(fallback.to_string()),
        _ => Err(anyhow!("unsafe path component: {raw}")),
    }
}

pub(crate) fn safe_relative_path(raw: &str) -> anyhow::Result<PathBuf> {
    let trimmed = raw.trim().trim_start_matches(&['/', '\\'][..]);
    let mut out = PathBuf::new();
    if trimmed.contains(':') {
        return Err(anyhow!("unsafe relative path: {raw}"));
    }
    for part in trimmed.split(|c| c == '/' || c == '\\') {
        let part = part.trim();
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            return Err(anyhow!("unsafe relative path: {raw}"));
        }
        out.push(part);
    }
    if out.as_os_str().is_empty() {
        return Err(anyhow!("empty relative path"));
    }
    Ok(out)
}

fn upload_safe_suffix(raw: &str) -> String {
    raw.chars().filter(|c| c.is_ascii_alphanumeric()).take(16).collect::<String>()
}
