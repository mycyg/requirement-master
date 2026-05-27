//! System tray with dynamic menu — mirrors the old Python tray menu structure.

use tauri::menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::tray::{MouseButton, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};

use crate::config::ConfigState;

pub fn install(app: &AppHandle) -> tauri::Result<()> {
    let cfg_state: tauri::State<ConfigState> = app.state();
    let cfg = cfg_state.read();
    let nick = if cfg.nickname.is_empty() { "未登录".to_string() } else { cfg.nickname.clone() };

    let user_label = MenuItemBuilder::with_id("user", format!("用户：{nick}")).enabled(false).build(app)?;
    let open_main = MenuItemBuilder::with_id("open_main", "打开主窗口").build(app)?;
    let open_hub = MenuItemBuilder::with_id("open_hub", "打开需求大厅").build(app)?;
    let open_current = MenuItemBuilder::with_id("open_current", "打开当前任务").build(app)?;
    let pull_new = MenuItemBuilder::with_id("pull_new", "立即拉新需求").build(app)?;
    let sync_drive = MenuItemBuilder::with_id("sync_drive", "立即同步网盘").build(app)?;
    let do_deliver = MenuItemBuilder::with_id("do_deliver", "完成并交付…").build(app)?;

    let avail_sub = SubmenuBuilder::new(app, "接单状态")
        .item(&MenuItemBuilder::with_id("avail_free", "空闲").build(app)?)
        .item(&MenuItemBuilder::with_id("avail_busy", "忙碌").build(app)?)
        .item(&MenuItemBuilder::with_id("avail_custom", "自定义…").build(app)?)
        .build()?;

    let drive_sub = SubmenuBuilder::new(app, "网盘同步")
        .item(&MenuItemBuilder::with_id("drive_off", "关").build(app)?)
        .item(&MenuItemBuilder::with_id("drive_download", "仅下载").build(app)?)
        .item(&MenuItemBuilder::with_id("drive_two_way", "双向同步").build(app)?)
        .build()?;

    let pause_label = if cfg.drive_sync_paused { "▶ 恢复同步" } else { "⏸ 暂停同步" };
    let pause_item = MenuItemBuilder::with_id("toggle_pause", pause_label).build(app)?;

    let settings = MenuItemBuilder::with_id("settings", "设置…").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "退出").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&user_label)
        .separator()
        .item(&open_main)
        .item(&open_hub)
        .item(&open_current)
        .separator()
        .item(&pull_new)
        .item(&sync_drive)
        .item(&do_deliver)
        .separator()
        .item(&avail_sub)
        .item(&drive_sub)
        .item(&pause_item)
        .separator()
        .item(&settings)
        .item(&PredefinedMenuItem::separator(app)?)
        .item(&quit)
        .build()?;

    let _tray = TrayIconBuilder::with_id("main-tray")
        .icon(app.default_window_icon().cloned().unwrap_or_default())
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, ev| {
            let id = ev.id.as_ref();
            match id {
                "open_main" | "open_hub" => navigate(app, "/"),
                "open_current" => navigate(app, "/current"),
                "pull_new" => { let _ = app.emit("tray-action", serde_json::json!({"action": "pull_new"})); }
                "sync_drive" => { let _ = app.emit("tray-action", serde_json::json!({"action": "sync_drive"})); }
                "do_deliver" => { let _ = app.emit("tray-action", serde_json::json!({"action": "do_deliver"})); }
                "avail_free" => set_availability(app, "free"),
                "avail_busy" => set_availability(app, "busy"),
                "avail_custom" => { let _ = app.emit("tray-action", serde_json::json!({"action": "avail_custom"})); }
                "drive_off" => set_drive_mode(app, "off", false),
                "drive_download" => set_drive_mode(app, "download", true),
                "drive_two_way" => set_drive_mode(app, "two_way", true),
                "toggle_pause" => toggle_pause(app),
                "settings" => navigate(app, "/settings"),
                "quit" => { app.exit(0); }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button, .. } = event {
                if matches!(button, MouseButton::Left) {
                    let app = tray.app_handle();
                    if let Some(w) = app.get_webview_window("main") {
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                }
            }
        })
        .build(app)?;

    Ok(())
}

fn navigate(app: &AppHandle, path: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    let _ = app.emit("navigate", serde_json::json!({ "path": path }));
}

fn set_availability(app: &AppHandle, status: &str) {
    let _ = app.emit("availability-change", serde_json::json!({ "status": status }));
    if let Some(s) = app.try_state::<ConfigState>() {
        let _ = s.write(|cfg| { cfg.availability_status = status.to_string(); });
    }
}

fn set_drive_mode(app: &AppHandle, mode: &str, enabled: bool) {
    if let Some(s) = app.try_state::<ConfigState>() {
        let _ = s.write(|cfg| {
            cfg.drive_sync_mode = mode.to_string();
            cfg.drive_sync_enabled = enabled;
        });
    }
}

fn toggle_pause(app: &AppHandle) {
    if let Some(s) = app.try_state::<ConfigState>() {
        let _ = s.write(|cfg| { cfg.drive_sync_paused = !cfg.drive_sync_paused; });
    }
}
