"""Provision the ASR service (Qwen3-ASR-1.7B) on the SSH target.

Prerequisites (run in order):
  1. scripts/setup_py313.py       — install Python 3.13 via uv
  2. scripts/download_models.py   — fetch the ASR model (~4.7 GB)
  3. scripts/install_cosy_deps.py — install torch / qwen_asr / etc.

This script detects the SSH user / home / py3.13 path on the remote, templates the
systemd unit accordingly, and brings the service up.

Idempotent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ssh_lib import connect, put_text, put_tree, run, sudo  # noqa: E402

ASR_DIR = "/srv/yqgl/asr_service"


def _remote_env(c) -> dict[str, str]:
    """Pull USER / HOME / PY313 from the SSH target."""
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

        print("\n== Sanity: py3.13 + torch + qwen_asr importable ==")
        run(c, f"{env['PY313']} -c 'import torch, qwen_asr, fastapi, uvicorn; print(\"ok\")'", check=True)

        print("\n== Ensure model is downloaded ==")
        run(c, f"test -d {env['HOME']}/.cache/modelscope/hub/models/Qwen/Qwen3-ASR-1___7B "
               "&& echo ok || (echo 'MISSING; run scripts/download_models.py first' && exit 1)",
            check=True)

        print("\n== Ensure asr_service dir ==")
        sudo(c, f"mkdir -p {ASR_DIR} && chown -R {env['USER']}:{env['USER']} {ASR_DIR} /srv/yqgl/data")

        print("\n== Upload asr_service/server.py ==")
        put_tree(c, ROOT / "asr_service", ASR_DIR,
                 exclude={"__pycache__", "requirements.txt"})

        print("\n== Template + install systemd unit ==")
        raw = (ROOT / "systemd" / "yqgl-asr.service").read_text(encoding="utf-8")
        unit = _template(raw, env)
        put_text(c, "/tmp/yqgl-asr.service", unit)
        sudo(c, "mv /tmp/yqgl-asr.service /etc/systemd/system/yqgl-asr.service "
                "&& chown root:root /etc/systemd/system/yqgl-asr.service "
                "&& chmod 644 /etc/systemd/system/yqgl-asr.service")
        sudo(c, "systemctl daemon-reload")
        sudo(c, "systemctl enable yqgl-asr.service")

        print("\n== Start ==")
        sudo(c, "systemctl restart yqgl-asr.service")
        run(c, "sleep 10 && systemctl is-active yqgl-asr.service "
               "&& tail -25 /srv/yqgl/data/asr.log", check=False)

        print("\nNext: scripts/test_asr.py to verify transcription end-to-end.")
    finally:
        c.close()


if __name__ == "__main__":
    main()
