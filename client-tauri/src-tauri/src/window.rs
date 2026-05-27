//! Main window decoration — Mica on Win11, Acrylic fallback, vibrancy on macOS.

use tauri::{Manager, Runtime};

#[cfg(target_os = "windows")]
use window_vibrancy::{apply_acrylic, apply_mica};

#[cfg(target_os = "macos")]
use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial, NSVisualEffectState};

pub fn decorate<R: Runtime>(app: &tauri::AppHandle<R>) {
    let Some(window) = app.get_webview_window("main") else { return };

    #[cfg(target_os = "windows")]
    {
        if apply_mica(&window, Some(true)).is_err() {
            let _ = apply_acrylic(&window, Some((255, 255, 255, 30)));
        }
    }

    #[cfg(target_os = "macos")]
    {
        let _ = apply_vibrancy(
            &window,
            NSVisualEffectMaterial::HudWindow,
            Some(NSVisualEffectState::Active),
            None,
        );
    }

    // After we've applied the effect, show the window.
    let _ = window.show();
}
