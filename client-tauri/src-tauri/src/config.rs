//! Persistent client config. Field names match the old Python `client/yqgl_tray.py`
//! so existing installations migrate without losing tokens or sync state.

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

use directories::{BaseDirs, ProjectDirs};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    #[serde(default = "default_server_ip")]
    pub server_ip: String,
    #[serde(default = "default_server_port")]
    pub server_port: u16,
    #[serde(default = "default_scheme")]
    pub server_scheme: String,
    #[serde(default)]
    pub server_url: String,
    #[serde(default)]
    pub nickname: String,
    #[serde(default)]
    pub cookie_token: String,
    #[serde(default)]
    pub client_token: String,
    #[serde(default = "default_sync_root")]
    pub sync_root: String,
    #[serde(default = "default_drive_sync_root")]
    pub drive_sync_root: String,
    #[serde(default)]
    pub drive_sync_enabled: bool,
    #[serde(default = "default_drive_sync_mode")]
    pub drive_sync_mode: String, // "off" | "download" | "two_way"
    #[serde(default)]
    pub drive_sync_paused: bool,
    #[serde(default = "default_availability")]
    pub availability_status: String,
    #[serde(default)]
    pub availability_text: Option<String>,
    #[serde(default = "default_reminder_offsets")]
    pub reminder_offsets_minutes: Vec<i64>,
    #[serde(default)]
    pub known_reqs: serde_json::Value,
    #[serde(default)]
    pub known_revision_requests: serde_json::Value,
    #[serde(default)]
    pub known_reminders: serde_json::Value,
    #[serde(default)]
    pub known_notifications: serde_json::Value,
    #[serde(default = "default_theme")]
    pub theme: String, // "auto" | "light" | "dark"
}

// Empty default — LAN IP varies per deployment; a stale hardcoded one
// sent fresh installs to a dead server. Onboarding's "下一步" button is
// disabled until the user enters & verifies a real IP.
fn default_server_ip() -> String { String::new() }
fn default_server_port() -> u16 { 8080 }
fn default_scheme() -> String { "http".into() }
#[cfg(target_os = "windows")]
fn default_sync_root() -> String { r"D:\工作需求".into() }
#[cfg(not(target_os = "windows"))]
fn default_sync_root() -> String {
    BaseDirs::new()
        .map(|d| d.home_dir().join("工作需求").to_string_lossy().to_string())
        .unwrap_or_else(|| "工作需求".into())
}
#[cfg(target_os = "windows")]
fn default_drive_sync_root() -> String { r"D:\工作需求\项目网盘".into() }
#[cfg(not(target_os = "windows"))]
fn default_drive_sync_root() -> String {
    PathBuf::from(default_sync_root()).join("项目网盘").to_string_lossy().to_string()
}
fn default_drive_sync_mode() -> String { "download".into() }
fn default_availability() -> String { "free".into() }
fn default_reminder_offsets() -> Vec<i64> { vec![1440, 120, 0] }
fn default_theme() -> String { "auto".into() }

impl Default for Config {
    fn default() -> Self {
        let mut c = Config {
            server_ip: default_server_ip(),
            server_port: default_server_port(),
            server_scheme: default_scheme(),
            server_url: String::new(),
            nickname: String::new(),
            cookie_token: String::new(),
            client_token: String::new(),
            sync_root: default_sync_root(),
            drive_sync_root: default_drive_sync_root(),
            drive_sync_enabled: false,
            drive_sync_mode: default_drive_sync_mode(),
            drive_sync_paused: false,
            availability_status: default_availability(),
            availability_text: None,
            reminder_offsets_minutes: default_reminder_offsets(),
            known_reqs: serde_json::json!({}),
            known_revision_requests: serde_json::json!({}),
            known_reminders: serde_json::json!({}),
            known_notifications: serde_json::json!({}),
            theme: default_theme(),
        };
        c.recompute_url();
        c
    }
}

impl Config {
    pub fn recompute_url(&mut self) {
        if self.server_url.is_empty() && !self.server_ip.trim().is_empty() {
            self.server_url = format!("{}://{}:{}", self.server_scheme, self.server_ip, self.server_port);
        }
    }

    /// Force-coerce any stale `two_way` setting back to `download`. The
    /// two-way mode was removed from the tray + UI but old config files
    /// (and `tauri build` packaged dev configs) may still hold the string.
    /// Without this coercion the user would land on Hub, the sync worker
    /// would log a hardcoded English error every 60s, and the picker UI
    /// has no way to set it back. Called from every Config entry point.
    pub fn normalize_drive_mode(&mut self) {
        if self.drive_sync_mode != "off" && self.drive_sync_mode != "download" {
            self.drive_sync_mode = "download".to_string();
        }
    }

    /// Drop notification/reminder dedup state. Called on logout, nickname
    /// change, or server-URL swap so a re-onboarded user sees fresh
    /// toasts rather than having yesterday's identity's dedup rows
    /// silently suppress legitimate first-time notifications.
    pub fn clear_dedup_state(&mut self) {
        self.known_reqs = serde_json::json!({});
        self.known_revision_requests = serde_json::json!({});
        self.known_reminders = serde_json::json!({});
        self.known_notifications = serde_json::json!({});
    }

    pub fn base_url(&self) -> String {
        if !self.server_url.is_empty() {
            self.server_url.trim_end_matches('/').to_string()
        } else {
            format!("{}://{}:{}", self.server_scheme, self.server_ip, self.server_port)
        }
    }

    /// Used by the Tauri setup hook to decide whether to route to onboarding.
    /// Kept on the Rust side so we can short-circuit window creation later.
    #[allow(dead_code)]
    pub fn is_complete(&self) -> bool {
        !self.nickname.is_empty() && !self.cookie_token.is_empty() && !self.client_token.is_empty()
    }
}

pub fn config_dir() -> Result<PathBuf> {
    let dirs = ProjectDirs::from("com", "mycyg", "yqgl")
        .ok_or_else(|| Error::Config("cannot resolve config dir".into()))?;
    Ok(dirs.config_dir().to_path_buf())
}

pub fn config_path() -> Result<PathBuf> { Ok(config_dir()?.join("config.json")) }

pub fn load() -> Result<Config> {
    let path = config_path()?;
    if !path.exists() {
        if let Some(legacy) = legacy_config_candidates().into_iter().find(|p| p.exists()) {
            if let Ok(raw) = fs::read_to_string(&legacy) {
                if let Ok(mut cfg) = serde_json::from_str::<Config>(&raw) {
                    cfg.recompute_url();
                    cfg.normalize_drive_mode();
                    if let Some(parent) = path.parent() {
                        fs::create_dir_all(parent)?;
                    }
                    fs::copy(&legacy, &path)?;
                    let backup = legacy.with_file_name("config.migrated-to-tauri.json");
                    let _ = fs::copy(&legacy, backup);
                    return Ok(cfg);
                }
            }
        }
        return Ok(Config::default());
    }
    let raw = fs::read_to_string(&path)?;
    // On parse failure, preserve the broken file as `config.broken-{ts}.json`
    // BEFORE falling back to defaults. Silent default-reset would log the
    // user out and a fresh onboarding revokes the existing device record
    // on the server — irreversible. Keeping the backup lets a human
    // (or a future repair tool) recover the tokens.
    let cfg = match serde_json::from_str::<Config>(&raw) {
        Ok(mut c) => { c.recompute_url(); c.normalize_drive_mode(); c }
        Err(e) => {
            tracing::warn!("config.json parse failed ({e}); preserving as .broken backup and using defaults");
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            let backup = path.with_file_name(format!("config.broken-{ts}.json"));
            let _ = fs::copy(&path, &backup);
            Config::default()
        }
    };
    // Keep the user's chosen server URL intact. Team installs default to the
    // 192.168.5.x subnet; legacy configs can be corrected from Settings.
    Ok(cfg)
}

fn legacy_config_candidates() -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Some(appdata) = std::env::var_os("APPDATA") {
        out.push(PathBuf::from(appdata).join("yqgl").join("config.json"));
    }
    if let Some(xdg) = std::env::var_os("XDG_CONFIG_HOME") {
        out.push(PathBuf::from(xdg).join("yqgl").join("config.json"));
    }
    if let Some(base) = BaseDirs::new() {
        out.push(base.config_dir().join("yqgl").join("config.json"));
    }
    out
}

pub fn save(cfg: &Config) -> Result<()> {
    let dir = config_dir()?;
    fs::create_dir_all(&dir)?;
    let path = dir.join("config.json");
    let pretty = serde_json::to_string_pretty(cfg)?;
    // Atomic write — write to .tmp then rename. A crash or power-loss
    // mid-write would otherwise leave config.json half-truncated; the
    // next `load()` falls back to `unwrap_or_default()` which silently
    // logs the user out and re-onboarding revokes the server-side device
    // token (one-way data loss).
    let tmp = dir.join("config.json.tmp");
    fs::write(&tmp, pretty)?;
    fs::rename(&tmp, &path)?;
    Ok(())
}

/// Shared mutable handle held in tauri::State.
///
/// Stores the inner Mutex behind an Arc + impls Clone so that workers
/// (SSE, reminders, spec_watch, uploads) and per-command snapshots all
/// share the SAME underlying Config. The previous design wrapped a
/// per-clone `Mutex<Config>` — writes via `set_config` in one task
/// were invisible to any other task holding a separate clone. That
/// meant `register_device` writing `client_token` into the tauri-managed
/// state did NOT propagate to the SSE / reminders loops, which kept
/// auth-empty until the app was restarted.
#[derive(Clone)]
pub struct ConfigState {
    inner: Arc<Mutex<Config>>,
}

impl ConfigState {
    pub fn from_disk() -> Self {
        // On a TRANSIENT IO failure (file locked by an antivirus
        // scanner, brief perm error, etc.) the previous `unwrap_or_default()`
        // silently dropped the user's tokens. Differentiate:
        //  - "file doesn't exist" → defaults, fine
        //  - "parse error" → defaults (load() already backs up the
        //    broken file to .broken-{ts}.json)
        //  - other (IO/lock/perms) → ALSO default but back the file up
        //    AND log loudly so it's recoverable. Never silently nuke.
        let cfg = match load() {
            Ok(c) => c,
            Err(e) => {
                tracing::error!(
                    "config load failed ({e}); using defaults. \
                     Your saved tokens are preserved if the original \
                     config.json is still readable on disk."
                );
                // Best-effort backup of whatever is on disk so the user
                // can recover by hand if needed.
                if let Ok(path) = config_path() {
                    if path.exists() {
                        let ts = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .map(|d| d.as_secs()).unwrap_or(0);
                        let backup = path.with_file_name(format!("config.recover-{ts}.json"));
                        let _ = fs::copy(&path, &backup);
                    }
                }
                Config::default()
            }
        };
        ConfigState { inner: Arc::new(Mutex::new(cfg)) }
    }
    pub fn read(&self) -> Config { self.inner.lock().clone() }
    pub fn write<F: FnOnce(&mut Config)>(&self, f: F) -> Result<Config> {
        let mut guard = self.inner.lock();
        f(&mut guard);
        guard.recompute_url();
        save(&guard)?;
        Ok(guard.clone())
    }
}
