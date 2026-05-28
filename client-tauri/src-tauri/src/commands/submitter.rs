//! 派活 / submitter-side Tauri commands. Thin shells over backend HTTP routes.
//!
//! Every command follows the same pattern as `requirements.rs`:
//!   1. Grab the configured `reqwest::Client` (with cookie jar and base url)
//!   2. Build the URL with `http::url`
//!   3. Attach the worker token via `http::with_auth` (so `require_local_client`
//!      gated endpoints — claim, sync, delivery, accept — authorise)
//!   4. Serialise body / parse response as `serde_json::Value`
//!
//! Keeping these as plain JSON pass-throughs means schema drift on the backend
//! doesn't immediately break compilation; the frontend handles shape.

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{AppHandle, State};

use crate::config::ConfigState;
use crate::error::Result;
use crate::http;
use crate::upload::{upload_file, UploadUrls};

/// Wrap the shared `State<ConfigState>` into a fresh `Arc<ConfigState>` so we
/// can move it into closures + futures without lifetime gymnastics. Matches
/// the pattern in [`crate::commands::delivery::start_delivery`].
fn arc_state(state: &State<'_, ConfigState>) -> Arc<ConfigState> {
    Arc::new(ConfigState(parking_lot::Mutex::new(state.read())))
}

// ---------- A. Reference data: projects, members ----------

#[tauri::command]
pub async fn list_my_projects(state: State<'_, ConfigState>) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/projects?state=active");
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn list_users(
    state: State<'_, ConfigState>,
    search: Option<String>,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let q = search.unwrap_or_default();
    let url = http::url(&state, &format!("/api/users?search={}", urlencoding::encode(&q)));
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

// ---------- B. Create / edit / dispatch / submit ----------

#[tauri::command]
pub async fn create_requirement(
    state: State<'_, ConfigState>,
    project_id: String,
    body: serde_json::Value,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/projects/{project_id}/requirements"));
    Ok(http::with_auth(client.post(&url), &state)
        .json(&body)
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn patch_planning(
    state: State<'_, ConfigState>,
    req_id: String,
    body: serde_json::Value,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/planning"));
    Ok(http::with_auth(client.patch(&url), &state)
        .json(&body)
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn patch_schedule(
    state: State<'_, ConfigState>,
    req_id: String,
    body: serde_json::Value,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/schedule"));
    Ok(http::with_auth(client.patch(&url), &state)
        .json(&body)
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn put_assignees(
    state: State<'_, ConfigState>,
    req_id: String,
    lead_user_id: Option<String>,
    collaborator_user_ids: Vec<String>,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/assignees"));
    Ok(http::with_auth(client.put(&url), &state)
        .json(&serde_json::json!({
            "lead_user_id": lead_user_id,
            "collaborator_user_ids": collaborator_user_ids,
        }))
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn submit_requirement(
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/submit"));
    Ok(http::with_auth(client.post(&url), &state)
        .send().await?
        .error_for_status()?
        .json().await?)
}

/// Composite: finalize the summary (so backend will accept submit) then submit.
/// This is what the wizard's "立即投递" button calls — skips the AI clarification
/// chat because the wizard already collected structured info.
#[tauri::command]
pub async fn finalize_and_submit(
    state: State<'_, ConfigState>,
    req_id: String,
    summary_md: Option<String>,
    title: Option<String>,
) -> Result<serde_json::Value> {
    let client = http::client(&state);

    let fin_url = http::url(&state, &format!("/api/requirements/{req_id}/finalize-summary"));
    http::with_auth(client.post(&fin_url), &state)
        .json(&serde_json::json!({ "summary_md": summary_md, "title": title }))
        .send().await?
        .error_for_status()?;

    let submit_url = http::url(&state, &format!("/api/requirements/{req_id}/submit"));
    Ok(http::with_auth(client.post(&submit_url), &state)
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn delete_requirement(
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<()> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}"));
    http::with_auth(client.delete(&url), &state)
        .send().await?
        .error_for_status()?;
    Ok(())
}

// ---------- G. Admin (managed-by-小光) ----------

#[tauri::command]
pub async fn set_user_admin(
    state: State<'_, ConfigState>,
    user_id: String,
    is_admin: bool,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/users/{user_id}/admin"));
    Ok(http::with_auth(client.put(&url), &state)
        .json(&serde_json::json!({ "is_admin": is_admin }))
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn create_project(
    state: State<'_, ConfigState>,
    name: String,
    slug: String,
    description: Option<String>,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, "/api/projects");
    Ok(http::with_auth(client.post(&url), &state)
        .json(&serde_json::json!({ "name": name, "slug": slug, "description": description }))
        .send().await?
        .error_for_status()?
        .json().await?)
}

#[tauri::command]
pub async fn delete_project(
    state: State<'_, ConfigState>,
    project_id: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/projects/{project_id}"));
    Ok(http::with_auth(client.delete(&url), &state)
        .send().await?
        .error_for_status()?
        .json().await?)
}

// ---------- F. Project Drive (shared per-project files) ----------

#[tauri::command]
pub async fn list_drive_root(
    state: State<'_, ConfigState>,
    project_id: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/projects/{project_id}/drive"));
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn upload_drive_item(
    app: AppHandle,
    state: State<'_, ConfigState>,
    project_id: String,
    file_path: String,
) -> Result<serde_json::Value> {
    let state_arc = arc_state(&state);
    let path = PathBuf::from(&file_path);
    let filename = path.file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "drop.bin".to_string());
    let mime = mime_guess::from_path(&path).first_or_octet_stream().essence_str().to_string();

    let proj_for_urls = project_id.clone();
    let urls = UploadUrls {
        init: {
            let s = state_arc.clone();
            let proj = proj_for_urls.clone();
            move || http::url(&s, &format!("/api/projects/{proj}/drive/upload/init"))
        },
        chunk: {
            let s = state_arc.clone();
            let proj = proj_for_urls.clone();
            move |idx: usize, upload_id: &str| http::url(
                &s,
                &format!("/api/projects/{proj}/drive/upload/{upload_id}/chunk/{idx}"),
            )
        },
        finalize: {
            let s = state_arc.clone();
            let proj = proj_for_urls.clone();
            move |upload_id: &str| http::url(
                &s,
                &format!("/api/projects/{proj}/drive/upload/{upload_id}/finalize"),
            )
        },
    };

    // Drive init needs `conflict` (auto-rename on duplicate so we never block).
    // `parent_id` omitted = upload to project root.
    let extras = serde_json::json!({ "conflict": "rename" });

    upload_file(
        &app,
        &state_arc,
        &project_id,  // tagged as the "channel" for upload-progress events
        &path,
        &filename,
        Some(&mime),
        urls,
        "drive-upload-progress",
        Some(extras),
    ).await
}

// ---------- D. Verification / revision (used by M5's ReviewDelivery) ----------

#[tauri::command]
pub async fn accept_requirement(
    state: State<'_, ConfigState>,
    req_id: String,
    note: Option<String>,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/accept"));
    let mut req = http::with_auth(client.post(&url), &state);
    if let Some(n) = note {
        req = req.json(&serde_json::json!({ "note_md": n }));
    }
    Ok(req.send().await?.error_for_status()?.json().await?)
}

// ---------- C. Submitter-side attachment upload + listing ----------

#[tauri::command]
pub async fn list_attachments(
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/attachments"));
    Ok(http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?)
}

#[tauri::command]
pub async fn upload_attachment(
    app: AppHandle,
    state: State<'_, ConfigState>,
    req_id: String,
    file_path: String,
) -> Result<serde_json::Value> {
    let state_arc = arc_state(&state);
    let path = PathBuf::from(&file_path);
    let filename = path.file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "upload.bin".to_string());
    let mime = mime_guess::from_path(&path).first_or_octet_stream().essence_str().to_string();

    let req_for_urls = req_id.clone();
    let s = state_arc.clone();
    let urls = UploadUrls {
        init: move || http::url(&s, &format!("/api/requirements/{req_for_urls}/upload/init")),
        chunk: {
            let s = state_arc.clone();
            let req = req_id.clone();
            move |idx: usize, upload_id: &str| http::url(
                &s,
                &format!("/api/requirements/{req}/upload/{upload_id}/chunk/{idx}"),
            )
        },
        finalize: {
            let s = state_arc.clone();
            let req = req_id.clone();
            move |upload_id: &str| http::url(
                &s,
                &format!("/api/requirements/{req}/upload/{upload_id}/finalize"),
            )
        },
    };

    upload_file(
        &app,
        &state_arc,
        &req_id,
        &path,
        &filename,
        Some(&mime),
        urls,
        "upload-progress",
        None,
    ).await
}

// ---------- E. Spec folder watcher ----------

#[tauri::command]
pub async fn start_spec_watcher(
    app: AppHandle,
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<String> {
    let state_arc = arc_state(&state);
    let folder = crate::spec_watch::start(app, state_arc, req_id).await?;
    Ok(folder.to_string_lossy().to_string())
}

#[tauri::command]
pub fn stop_spec_watcher(req_id: String) {
    crate::spec_watch::stop(&req_id);
}

#[tauri::command]
pub async fn open_spec_folder(
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<()> {
    // Re-derive project_slug + code so we don't need to round-trip in JS.
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}"));
    let meta: serde_json::Value = http::with_auth(client.get(&url), &state)
        .send().await?.error_for_status()?.json().await?;
    let slug = meta.get("project_slug").and_then(|v| v.as_str()).unwrap_or("unknown");
    let code = meta.get("code").and_then(|v| v.as_str()).unwrap_or(&req_id);

    let sync_root = state.read().sync_root.clone();
    let path = PathBuf::from(&sync_root).join(slug).join(code).join("spec");
    std::fs::create_dir_all(&path)?;

    crate::commands::shell::open_folder(path.to_string_lossy().to_string())
}

#[tauri::command]
pub async fn download_delivery(
    state: State<'_, ConfigState>,
    req_id: String,
) -> Result<serde_json::Value> {
    use std::io::Write;
    let client = http::client(&state);

    // 1. find the latest delivery for this requirement
    let list_url = http::url(&state, &format!("/api/requirements/{req_id}/deliveries"));
    let deliveries: serde_json::Value = http::with_auth(client.get(&list_url), &state)
        .send().await?.error_for_status()?.json().await?;
    let arr = deliveries.as_array()
        .ok_or_else(|| crate::error::Error::Other("deliveries response not an array".into()))?;
    let latest = arr.iter()
        .max_by_key(|d| d.get("round").and_then(|r| r.as_i64()).unwrap_or(0))
        .ok_or_else(|| crate::error::Error::Other("no deliveries yet".into()))?;
    let delivery_id = latest.get("id").and_then(|v| v.as_str())
        .ok_or_else(|| crate::error::Error::Other("delivery missing id".into()))?
        .to_string();
    let round = latest.get("round").and_then(|v| v.as_i64()).unwrap_or(1);

    // 2. Look up project_slug + code so we know where on disk to drop the zip.
    let req_url = http::url(&state, &format!("/api/requirements/{req_id}"));
    let req_meta: serde_json::Value = http::with_auth(client.get(&req_url), &state)
        .send().await?.error_for_status()?.json().await?;
    let slug = req_meta.get("project_slug").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
    let code = req_meta.get("code").and_then(|v| v.as_str()).unwrap_or(&req_id).to_string();

    let sync_root = state.read().sync_root.clone();
    let dest_dir = PathBuf::from(&sync_root).join(&slug).join(&code).join("deliveries");
    std::fs::create_dir_all(&dest_dir)?;
    let dest_path = dest_dir.join(format!("round-{round}.zip"));

    // 3. Stream the package to disk.
    let dl_url = http::url(&state, &format!("/api/deliveries/{delivery_id}/package"));
    let mut resp = http::with_auth(client.get(&dl_url), &state)
        .send().await?.error_for_status()?;
    let mut f = std::fs::File::create(&dest_path)?;
    while let Some(chunk) = resp.chunk().await? {
        f.write_all(&chunk)?;
    }

    Ok(serde_json::json!({
        "delivery_id": delivery_id,
        "round": round,
        "saved_path": dest_path.to_string_lossy(),
    }))
}

#[tauri::command]
pub async fn request_revision(
    state: State<'_, ConfigState>,
    req_id: String,
    reason_md: String,
) -> Result<serde_json::Value> {
    let client = http::client(&state);
    let url = http::url(&state, &format!("/api/requirements/{req_id}/revisions"));
    Ok(http::with_auth(client.post(&url), &state)
        .json(&serde_json::json!({ "reason_md": reason_md }))
        .send().await?
        .error_for_status()?
        .json().await?)
}
