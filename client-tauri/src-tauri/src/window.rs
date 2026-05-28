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
        // Acrylic = true semi-transparent blur (real-time, sees the desktop
        // + other windows through the blur), much closer to the macOS Dock
        // look than Mica (which uses the wallpaper as a static texture).
        // Tint = light wash on top so the dark theme still has some lift.
        if apply_acrylic(&window, Some((255, 255, 255, 18))).is_err() {
            // Older Win11 builds may have deprecated Acrylic — fall back to
            // base Mica (light variant: `false`) which is gentler than MicaAlt.
            let _ = apply_mica(&window, Some(false));
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
