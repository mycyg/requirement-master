//! Handle yqgl:// URLs. yqgl://r/{id} → emit `navigate` to /r/{id}.

use tauri::{AppHandle, Emitter, Manager};

// Whitelist of host segments — anything else is rejected. React Router
// only knows these route prefixes, so allowing arbitrary hosts opens
// path-injection vectors (e.g. `yqgl://r/../../settings`) AND wastes
// our IPC bandwidth on URLs no view will respond to.
const ALLOWED_HOSTS: &[&str] = &["r", "p", "inbox", "settings", "me"];

pub fn handle(app: &AppHandle, url: &str) {
    let Some(u) = url::Url::parse(url).ok() else { return };
    let Some(host) = u.host_str() else { return };
    if !ALLOWED_HOSTS.contains(&host) {
        tracing::warn!("deep-link rejected unknown host: {host}");
        return;
    }
    // Strip any `..` or `//` traversal segments from the path. Without this
    // a crafted `yqgl://r/..%2F..%2Fsettings` would reach React Router as
    // `/r/../../settings`, and any view that does `fetch("/api" + path)`
    // would be susceptible to path traversal.
    let raw_path = u.path();
    let safe_segments: Vec<&str> = raw_path
        .split('/')
        .filter(|seg| !seg.is_empty() && *seg != "." && *seg != "..")
        .collect();
    let path = format!("/{}/{}", host, safe_segments.join("/"));
    let clean_path = path.trim_end_matches('/').to_string();
    let final_path = if clean_path.is_empty() { format!("/{host}") } else { clean_path };

    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    let _ = app.emit("navigate", serde_json::json!({ "path": final_path }));
    // Only emit the sanitized path on `deep-link`; never the raw URL with
    // its fragment / query (would XSS if any view ever did
    // `window.location.hash = evt.payload.url`).
    let _ = app.emit("deep-link", serde_json::json!({ "path": final_path }));
}
