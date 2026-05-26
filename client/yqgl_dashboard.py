"""独立 dashboard 窗口（用 pywebview 包一层 Edge WebView2）。

由 yqgl_tray.py 的菜单以子进程方式启动，不阻塞 pystray 主循环。

读取 %APPDATA%\\yqgl\\config.json 拿 server_url + cookie_token，
打开 <server_url>/dashboard。Cookie 通过 Set-Cookie 头预注入。
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
    nickname: str = cfg.get("nickname", "")

    try:
        import webview
    except ImportError:
        print("pywebview not installed; pip install pywebview", file=sys.stderr)
        sys.exit(1)

    # Pre-set the cookie on the host before loading the page.
    from urllib.parse import urlparse
    host = urlparse(server_url).hostname or "localhost"

    js_set_cookie = f"""
    (() => {{
      document.cookie = "yqgl_id={cookie_token}; path=/; domain={host}";
      // also nav to /dashboard if we landed on root
      if (location.pathname === '/' || location.pathname === '') {{
        location.replace('/dashboard');
      }}
    }})();
    """

    window = webview.create_window(
        f"需求管理大师 · 接单看板 · {nickname}",
        url=f"{server_url}/dashboard",
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
