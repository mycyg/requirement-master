//! Handle yqgl:// URLs. yqgl://r/{id} → emit `navigate` to /r/{id}.

use tauri::{AppHandle, Emitter, Manager};

pub fn handle(app: &AppHandle, url: &str) {
    let parsed = url::Url::parse(url).ok();
    if let Some(u) = parsed {
        let path = if let Some(host) = u.host_str() {
            format!("/{}{}", host, u.path())
        } else {
            u.path().to_string()
        };
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.show();
            let _ = w.set_focus();
        }
        let _ = app.emit("navigate", serde_json::json!({ "path": path }));
        let _ = app.emit("deep-link", serde_json::json!({ "url": url, "path": path }));
    }
}
