"""Provision ASR using the existing Python 3.13 user-site (where torch + qwen_asr already live).

No fresh torch download needed. setup_py313.py must have been run first to ensure
Python 3.13 is installed via uv.

Idempotent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ssh_lib import connect, put_text, put_tree, run, sudo  # noqa: E402

ASR_DIR = "/srv/yqgl/asr_service"
PY313 = "/home/mycyg/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13"


def main() -> None:
    c = connect()
    try:
        print("== Sanity: py3.13 + torch + qwen_asr importable ==")
        run(c, f"{PY313} -c 'import torch, qwen_asr, fastapi, uvicorn; print(\"ok\")'", check=True)

        print("\n== Clean up the wasted asr-venv from earlier attempt ==")
        run(c, "rm -rf /srv/yqgl/asr-venv && echo cleaned", check=False)

        print("\n== Ensure asr_service dir ==")
        sudo(c, f"mkdir -p {ASR_DIR} && chown -R mycyg:mycyg {ASR_DIR}")

        print("\n== Upload asr_service/server.py ==")
        put_tree(c, ROOT / "asr_service", ASR_DIR, exclude={"__pycache__", "requirements.txt"})

        print("\n== Install / refresh systemd unit ==")
        unit = (ROOT / "systemd" / "yqgl-asr.service").read_text(encoding="utf-8")
        put_text(c, "/tmp/yqgl-asr.service", unit)
        sudo(c, "mv /tmp/yqgl-asr.service /etc/systemd/system/yqgl-asr.service && chown root:root /etc/systemd/system/yqgl-asr.service && chmod 644 /etc/systemd/system/yqgl-asr.service")
        sudo(c, "systemctl daemon-reload")
        sudo(c, "systemctl enable yqgl-asr.service")

        print("\n== Start (model loads ~30s the first time) ==")
        sudo(c, "systemctl restart yqgl-asr.service")
        print("Sleeping 10s for boot…")
        run(c, "sleep 10 && systemctl is-active yqgl-asr.service && tail -25 /srv/yqgl/data/asr.log", check=False)

        print("\nNext: scripts/test_asr.py to wait-for-ready and transcribe.")
    finally:
        c.close()


if __name__ == "__main__":
    main()
