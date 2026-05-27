"""独立本地工作台窗口（用 pywebview 包一层 Edge/WebKit）。

由 yqgl_tray.py 的菜单以子进程方式启动，不阻塞 pystray 主循环。

读取 %APPDATA%\\yqgl\\config.json 拿 server_url + cookie_token + client_token，
打开 <server_url>/local-workbench，并把本地端能力注入到 localStorage。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "yqgl"
CFG_PATH = APP_DIR / "config.json"


def main() -> None:
    if not CFG_PATH.exists():
        print("config not found; run the tray once to configure", file=sys.stderr)
        sys.exit(1)

    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    server_url: str = cfg["server_url"]
    cookie_token: str = cfg.get("cookie_token", "")
    client_token: str = cfg.get("client_token", "")
    nickname: str = cfg.get("nickname", "")

    try:
        import webview
    except ImportError:
        print("pywebview not installed; pip install pywebview", file=sys.stderr)
        sys.exit(1)

    js_set_cookie = f"""
    (() => {{
      document.cookie = "yqgl_id=" + {json.dumps(cookie_token)} + "; path=/";
      localStorage.setItem("yqgl_runtime", "desktop");
      localStorage.setItem("yqgl_client_token", {json.dumps(client_token)});
      localStorage.setItem("yqgl_client_nickname", {json.dumps(nickname)});
      if (!sessionStorage.getItem("yqgl_desktop_bootstrapped")) {{
        sessionStorage.setItem("yqgl_desktop_bootstrapped", "1");
        location.replace("/local-workbench");
        return;
      }}
      if (location.pathname === '/' || location.pathname === '') {{
        location.replace('/local-workbench');
      }}
    }})();
    """

    window = webview.create_window(
        f"需求管理大师 · 本地工作台 · {nickname}",
        url=f"{server_url}/local-workbench",
        width=1200,
        height=800,
        resizable=True,
        on_top=False,
    )

    def on_loaded() -> None:
        try:
            window.evaluate_js(js_set_cookie)
        except Exception:
            pass

    window.events.loaded += on_loaded
    webview.start()


if __name__ == "__main__":
    main()
