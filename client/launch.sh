#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

nohup "$PY" yqgl_tray.py >/tmp/yqgl-tray.log 2>&1 &
echo "需求管理大师客户端已启动，日志：/tmp/yqgl-tray.log"
