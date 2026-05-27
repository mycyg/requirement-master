//! Persistent client config. Field names match the old Python `client/yqgl_tray.py`
//! so existing installations migrate without losing tokens or sync state.

use std::fs;
use std::path::PathBuf;

use directories::ProjectDirs;
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

fn default_server_ip() -> String { "192.168.0.224".into() }
fn default_server_port() -> u16 { 8080 }
fn default_scheme() -> String { "http".into() }
fn default_sync_root() -> String { r"D:\工作需求".into() }
fn default_drive_sync_root() -> String { r"D:\工作需求\项目网盘".into() }
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
        if self.server_url.is_empty() {
            self.server_url = format!("{}://{}:{}", self.server_scheme, self.server_ip, self.server_port);
        }
    }

    pub fn base_url(&self) -> String {
        if !self.server_url.is_empty() {
            self.server_url.trim_end_matches('/').to_string()
        } else {
            format!("{}://{}:{}", self.server_scheme, self.server_ip, self.server_port)
        }
    }

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
        return Ok(Config::default());
    }
    let raw = fs::read_to_string(&path)?;
    let mut cfg: Config = serde_json::from_str(&raw).unwrap_or_default();
    // Auto-migrate the old 192.168.5.x default to 192.168.0.x lan prefix.
    if cfg.server_ip.starts_with("192.168.5.") {
        cfg.server_ip = cfg.server_ip.replacen("192.168.5.", "192.168.0.", 1);
        cfg.server_url = String::new();
    }
    cfg.recompute_url();
    Ok(cfg)
}

pub fn save(cfg: &Config) -> Result<()> {
    let dir = config_dir()?;
    fs::create_dir_all(&dir)?;
    let path = dir.join("config.json");
    let pretty = serde_json::to_string_pretty(cfg)?;
    fs::write(path, pretty)?;
    Ok(())
}

/// Shared mutable handle held in tauri::State.
pub struct ConfigState(pub Mutex<Config>);

impl ConfigState {
    pub fn from_disk() -> Self {
        let cfg = load().unwrap_or_default();
        ConfigState(Mutex::new(cfg))
    }
    pub fn read(&self) -> Config { self.0.lock().clone() }
    pub fn write<F: FnOnce(&mut Config)>(&self, f: F) -> Result<Config> {
        let mut guard = self.0.lock();
        f(&mut guard);
        guard.recompute_url();
        save(&guard)?;
        Ok(guard.clone())
    }
}
