#!/usr/bin/env bash
set -euo pipefail

SERVER="${YQGL_SERVER:-http://192.168.5.53:8080}"
INSTALL_DIR="${YQGL_CLIENT_DIR:-$HOME/.local/share/yqgl-client}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/yqgl"
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

python - "$SERVER" "$CONFIG_DIR/config.json" <<'PY'
import json
import pathlib
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
