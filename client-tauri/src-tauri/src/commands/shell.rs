use std::path::{Component, Path, PathBuf};

use tauri::State;

use crate::config::ConfigState;
use crate::error::{Error, Result};

/// Open a folder in the OS file browser.
///
/// SECURITY: The JS layer can pass any string. Without validation, a
/// compromised webview (XSS in attachment preview, malicious deep-link
/// payload, etc.) could pass `cmd.exe /c <evil>` and the underlying
/// `explorer.exe` / `open` / `xdg-open` would happily launch it.
///
/// Mitigations:
/// 1. Reject paths containing shell metacharacters / control characters /
///    embedded NULs that some shells re-parse.
/// 2. Require the canonical path to live UNDER one of the user's
///    configured roots (`sync_root`, `drive_sync_root`, or the YQGL
///    config dir). Anything outside is refused.
/// 3. Spawn with the path as a single argv arg (`Command::arg`) so even
///    if `;` / `&&` slipped past #1, the OS file opener doesn't re-parse.
#[tauri::command]
pub fn open_folder(state: State<'_, ConfigState>, path: String) -> Result<()> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err(Error::Other("open_folder: empty path".into()));
    }
    // Reject embedded control chars, shell metacharacters, and obvious
    // injection attempts before we do any FS work.
    if trimmed.chars().any(|c| {
        c == '\0' || c == '\n' || c == '\r' || c == '|' || c == ';' || c == '&'
            || c == '<' || c == '>' || c == '"' || c == '`' || c == '$' || c == '\x1b'
    }) {
        return Err(Error::Other("open_folder: path contains disallowed characters".into()));
    }

    let target = PathBuf::from(trimmed);
    // Reject paths with `..` segments — they could escape an allowed root
    // even after canonicalization if the root itself contains a symlink.
    if target.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err(Error::Other("open_folder: path traversal rejected".into()));
    }

    let cfg = state.read();
    let mut roots: Vec<PathBuf> = Vec::new();
    if !cfg.sync_root.trim().is_empty() {
        roots.push(PathBuf::from(&cfg.sync_root));
    }
    if !cfg.drive_sync_root.trim().is_empty() {
        roots.push(PathBuf::from(&cfg.drive_sync_root));
    }
    if let Ok(cfg_dir) = crate::config::config_dir() {
        roots.push(cfg_dir);
    }
    drop(cfg);

    // We accept a path that doesn't yet exist (typical first-time-on-a-task
    // case — user clicks "Open Folder" before any file has been synced
    // into it). Canonicalize() requires the path to exist, so we walk up
    // to the nearest existing ancestor and canonicalize THAT, then append
    // the still-non-existent tail. This produces a canonical-form path
    // (e.g. `\\?\D:\…` on Windows) that compares cleanly against the
    // canonicalized roots — without it, the raw `D:\…` target fails the
    // `starts_with(\\?\D:\…)` check and every "Open Folder" click 500s.
    fn canonicalize_with_existing_ancestor(p: &Path) -> PathBuf {
        let mut existing: PathBuf = p.to_path_buf();
        let mut tail: Vec<std::ffi::OsString> = Vec::new();
        loop {
            match existing.canonicalize() {
                Ok(canon) => {
                    let mut out = canon;
                    for seg in tail.iter().rev() {
                        out.push(seg);
                    }
                    return out;
                }
                Err(_) => {
                    let file_name = existing.file_name().map(|s| s.to_os_string());
                    if !existing.pop() || file_name.is_none() {
                        // Ran off the top — give up and return as-is.
                        return p.to_path_buf();
                    }
                    if let Some(name) = file_name {
                        tail.push(name);
                    }
                }
            }
        }
    }

    let canon_target: PathBuf = canonicalize_with_existing_ancestor(&target);

    let allowed = roots.iter().any(|root| {
        let canon_root = canonicalize_with_existing_ancestor(root);
        canon_target.starts_with(&canon_root)
    });
    if !allowed {
        return Err(Error::Other(format!(
            "open_folder: path is not under any configured workspace root: {}",
            canon_target.display()
        )));
    }

    let arg = canon_target.as_os_str();
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer").arg(arg).spawn().ok();
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open").arg(arg).spawn().ok();
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        std::process::Command::new("xdg-open").arg(arg).spawn().ok();
    }
    let _ = Path::new("");  // suppress unused-import warning when only one cfg branch compiles
    Ok(())
}
