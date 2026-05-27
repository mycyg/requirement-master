#!/usr/bin/env bash
set -euo pipefail

SERVER="${YQGL_SERVER:-http://192.168.5.53:8080}"
INSTALL_DIR="${YQGL_CLIENT_DIR:-$HOME/.local/share/yqgl-client}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/yqgl"
DESKTOP_DIR="${YQGL_DESKTOP_DIR:-$HOME/Desktop}"
AUTOSTART_DIR="${YQGL_AUTOSTART_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/autostart}"
PYTHON_BIN="${PYTHON:-python3}"

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
echo "Installing yqgl client to $INSTALL_DIR"

if [ -f "$(dirname "$0")/yqgl_tray.py" ]; then
  cp -R "$(dirname "$0")/"* "$INSTALL_DIR/"
else
  curl -fsSL "$SERVER/client/yqgl_tray.py" -o "$INSTALL_DIR/yqgl_tray.py"
  curl -fsSL "$SERVER/client/yqgl_dashboard.py" -o "$INSTALL_DIR/yqgl_dashboard.py"
  curl -fsSL "$SERVER/client/requirements.txt" -o "$INSTALL_DIR/requirements.txt"
  curl -fsSL "$SERVER/client/launch.sh" -o "$INSTALL_DIR/launch.sh"
fi

cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
chmod +x "$INSTALL_DIR/launch.sh"

mkdir -p "$DESKTOP_DIR" "$AUTOSTART_DIR"
cat > "$DESKTOP_DIR/需求管理大师.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=需求管理大师 本地工作台
Comment=打开需求管理大师本地客户端
Exec=$INSTALL_DIR/launch.sh
Path=$INSTALL_DIR
Terminal=false
Categories=Office;
EOF
chmod +x "$DESKTOP_DIR/需求管理大师.desktop"
cp "$DESKTOP_DIR/需求管理大师.desktop" "$AUTOSTART_DIR/yqgl.desktop"

python - "$SERVER" "$CONFIG_DIR/config.json" <<'PY'
import json
import pathlib
import platform
import sys
from urllib.parse import urlparse

server = sys.argv[1]
target = pathlib.Path(sys.argv[2])
parsed = urlparse(server)
root = str(pathlib.Path.home() / "工作需求")
config = {
    "server_url": server,
    "server_scheme": parsed.scheme or "http",
    "server_ip": parsed.hostname or "192.168.5.53",
    "server_port": parsed.port or 8080,
    "client_token": "",
    "client_device_id": "",
    "client_device_name": platform.node() or "本地工作台",
    "project_save_root": root,
    "sync_root": root,
    "drive_sync_root": str(pathlib.Path(root) / "项目网盘"),
    "drive_sync_enabled": False,
    "drive_sync_mode": "download",
    "availability_status": "free",
    "availability_text": "",
}
target.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "Installed. Start with:"
echo "  $INSTALL_DIR/launch.sh"
echo "Desktop launcher and autostart entry created."
