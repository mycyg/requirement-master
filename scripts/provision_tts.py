"""Deploy the TTS service (CosyVoice). Idempotent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ssh_lib import connect, put_text, put_tree, run, sudo  # noqa: E402

TTS_DIR = "/srv/yqgl/tts_service"


def main() -> None:
    c = connect()
    try:
        print("== Sanity: CosyVoice import works ==")
        run(c, "/home/mycyg/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13 -c \""
              "import sys; "
              "sys.path.insert(0, '/home/mycyg/CosyVoice/third_party/Matcha-TTS'); "
              "sys.path.insert(0, '/home/mycyg/CosyVoice'); "
              "from cosyvoice.cli.cosyvoice import CosyVoice3; "
              "print('ok')\"", check=True)

        print("\n== Ensure tts_service dir ==")
        sudo(c, f"mkdir -p {TTS_DIR} && chown -R mycyg:mycyg {TTS_DIR}")

        print("\n== Upload tts_service/server.py ==")
        put_tree(c, ROOT / "tts_service", TTS_DIR, exclude={"__pycache__"})

        print("\n== Install / refresh systemd unit ==")
        unit = (ROOT / "systemd" / "yqgl-tts.service").read_text(encoding="utf-8")
        put_text(c, "/tmp/yqgl-tts.service", unit)
        sudo(c, "mv /tmp/yqgl-tts.service /etc/systemd/system/yqgl-tts.service && chown root:root /etc/systemd/system/yqgl-tts.service && chmod 644 /etc/systemd/system/yqgl-tts.service")
        sudo(c, "systemctl daemon-reload")
        sudo(c, "systemctl enable yqgl-tts.service")

        print("\n== Start (CosyVoice loads ~9s) ==")
        sudo(c, "systemctl restart yqgl-tts.service")
        run(c, "sleep 15 && systemctl is-active yqgl-tts.service && tail -30 /srv/yqgl/data/tts.log", check=False)

        print("\n== /health probe ==")
        run(c, "curl -s http://127.0.0.1:8002/health", check=False)

        print("\n== Generate test wav ==")
        run(c, "curl -sS -X POST -H 'Content-Type: application/json' "
              "-d '{\"text\":\"你好，欢迎使用需求管理大师。\",\"voice\":\"male\"}' "
              "http://127.0.0.1:8002/tts -o /tmp/yqgl_tts_test.wav && "
              "ls -la /tmp/yqgl_tts_test.wav && "
              "file /tmp/yqgl_tts_test.wav", check=False, timeout=60)
    finally:
        c.close()


if __name__ == "__main__":
    main()
