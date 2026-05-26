"""Provision the TTS service (CosyVoice3) on the SSH target.

Prerequisites (run in order):
  1. scripts/setup_py313.py
  2. scripts/download_models.py
  3. scripts/install_cosy_deps.py

Detects SSH user / home / py3.13 path, templates the systemd unit, brings service up.

Idempotent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ssh_lib import connect, put_text, put_tree, run, sudo  # noqa: E402

TTS_DIR = "/srv/yqgl/tts_service"


def _remote_env(c) -> dict[str, str]:
    rc, user, _ = run(c, "whoami", check=True, quiet=True)
    user = user.strip()
    rc, home, _ = run(c, "echo $HOME", check=True, quiet=True)
    home = home.strip()
    rc, py, _ = run(c, "~/.local/bin/uv python find 3.13 2>/dev/null || echo MISSING",
                     check=False, quiet=True)
    py = py.strip().splitlines()[-1] if py.strip() else "MISSING"
    if "MISSING" in py:
        sys.exit("Python 3.13 not installed; run scripts/setup_py313.py first")
    return {"USER": user, "HOME": home, "PY313": py}


def _template(text: str, env: dict[str, str]) -> str:
    for k, v in env.items():
        text = text.replace(f"{{{{{k}}}}}", v)
    return text


def main() -> None:
    c = connect()
    try:
        env = _remote_env(c)
        print(f"Detected: USER={env['USER']}  HOME={env['HOME']}  PY313={env['PY313']}")

        print("\n== Sanity: CosyVoice repo + model present ==")
        run(c, f"test -d {env['HOME']}/CosyVoice/.git "
               "&& echo repo-ok || (echo 'MISSING; run scripts/download_models.py first' && exit 1)",
            check=True)
        run(c, f"test -d {env['HOME']}/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B "
               "&& echo model-ok || (echo 'MISSING model dir' && exit 1)",
            check=True)

        print("\n== Sanity: CosyVoice import ==")
        run(c, f"{env['PY313']} -c \""
              f"import sys; "
              f"sys.path.insert(0, '{env['HOME']}/CosyVoice/third_party/Matcha-TTS'); "
              f"sys.path.insert(0, '{env['HOME']}/CosyVoice'); "
              "from cosyvoice.cli.cosyvoice import CosyVoice3; "
              "print('ok')\"",
            check=True)

        print("\n== Ensure tts_service dir ==")
        sudo(c, f"mkdir -p {TTS_DIR} && chown -R {env['USER']}:{env['USER']} {TTS_DIR} /srv/yqgl/data")

        print("\n== Upload tts_service/server.py ==")
        put_tree(c, ROOT / "tts_service", TTS_DIR,
                 exclude={"__pycache__", "requirements.txt"})

        print("\n== Template + install systemd unit ==")
        raw = (ROOT / "systemd" / "yqgl-tts.service").read_text(encoding="utf-8")
        unit = _template(raw, env)
        put_text(c, "/tmp/yqgl-tts.service", unit)
        sudo(c, "mv /tmp/yqgl-tts.service /etc/systemd/system/yqgl-tts.service "
                "&& chown root:root /etc/systemd/system/yqgl-tts.service "
                "&& chmod 644 /etc/systemd/system/yqgl-tts.service")
        sudo(c, "systemctl daemon-reload")
        sudo(c, "systemctl enable yqgl-tts.service")

        print("\n== Start (CosyVoice loads ~9s) ==")
        sudo(c, "systemctl restart yqgl-tts.service")
        run(c, "sleep 15 && systemctl is-active yqgl-tts.service "
               "&& tail -30 /srv/yqgl/data/tts.log", check=False)

        print("\n== /health probe ==")
        run(c, "curl -s http://127.0.0.1:8002/health", check=False)

        print("\n== Generate test wav ==")
        run(c, "curl -sS -X POST -H 'Content-Type: application/json' "
               "-d '{\"text\":\"你好，欢迎使用需求管理大师。\",\"voice\":\"male\"}' "
               "http://127.0.0.1:8002/tts -o /tmp/yqgl_tts_test.wav "
               "&& ls -la /tmp/yqgl_tts_test.wav && file /tmp/yqgl_tts_test.wav",
            check=False, timeout=60)
    finally:
        c.close()


if __name__ == "__main__":
    main()
