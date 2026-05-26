"""One-time server bootstrap.

Idempotent: safe to re-run. Performs:
  1. Install uv (per-user) if missing
  2. Install Python 3.12 via uv
  3. Create /srv/yqgl/{app,data,web,deliveries,uploads,voice,outputs} and chown to mycyg
  4. Create /srv/yqgl/venv (Python 3.12) and install app deps
  5. Install /etc/systemd/system/yqgl-web.service (asr unit installed in M1)
  6. systemctl daemon-reload + enable yqgl-web

Run: python scripts/provision.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ssh_lib import connect, put_file, put_text, run, sudo  # noqa: E402


REMOTE_ROOT = "/srv/yqgl"
APP_DIR = f"{REMOTE_ROOT}/app"
VENV_DIR = f"{REMOTE_ROOT}/venv"
DATA_DIR = f"{REMOTE_ROOT}/data"


def main() -> None:
    client = connect()
    try:
        print("== 1. Install uv if missing ==")
        rc, _, _ = run(client, "command -v ~/.local/bin/uv", check=False, quiet=True)
        if rc != 0:
            run(client, "curl -LsSf https://astral.sh/uv/install.sh | sh")
        else:
            print("uv already installed")

        print("\n== 2. Install Python 3.12 via uv ==")
        run(client, "~/.local/bin/uv python install 3.12")

        print("\n== 3. Create /srv/yqgl tree ==")
        sudo(client, f"mkdir -p {APP_DIR} {DATA_DIR}/uploads {DATA_DIR}/voice {DATA_DIR}/outputs {DATA_DIR}/deliveries {REMOTE_ROOT}/web/dist")
        sudo(client, f"chown -R mycyg:mycyg {REMOTE_ROOT}")

        print("\n== 4. Create venv + install deps ==")
        rc, _, _ = run(client, f"test -f {VENV_DIR}/bin/python", check=False, quiet=True)
        if rc != 0:
            run(client, f"~/.local/bin/uv venv --python 3.12 {VENV_DIR}")
        put_file(client, ROOT / "app" / "pyproject.toml", f"{APP_DIR}/pyproject.toml")
        run(client, f"{VENV_DIR}/bin/python -m ensurepip --upgrade", check=False, quiet=True)
        run(client, f"{VENV_DIR}/bin/python -m pip install --upgrade pip")
        run(client, f"{VENV_DIR}/bin/pip install fastapi 'uvicorn[standard]' sqlalchemy alembic pydantic pydantic-settings python-multipart itsdangerous httpx anthropic pillow")
        # markitdown is heavy and pulls many transitives; install separately so a failure here doesn't block hello-world
        rc, _, _ = run(client, f"{VENV_DIR}/bin/pip install 'markitdown[all]'", check=False)
        if rc != 0:
            print("[warn] markitdown install failed; will retry in M3")

        print("\n== 5. Install systemd unit (web only; ASR added in M1) ==")
        unit = (ROOT / "systemd" / "yqgl-web.service").read_text(encoding="utf-8")
        put_text(client, "/tmp/yqgl-web.service", unit)
        sudo(client, "mv /tmp/yqgl-web.service /etc/systemd/system/yqgl-web.service && chown root:root /etc/systemd/system/yqgl-web.service && chmod 644 /etc/systemd/system/yqgl-web.service")
        sudo(client, "systemctl daemon-reload")
        sudo(client, "systemctl enable yqgl-web.service")

        print("\n== 6. Open firewall for 8080 (idempotent; only if ufw active) ==")
        rc, out, _ = sudo(client, "ufw status 2>/dev/null | head -1", check=False)
        if "active" in out.lower():
            sudo(client, "ufw allow 8080/tcp", check=False)
        else:
            print("ufw inactive; skipping")

        print("\n== Done. Run scripts/deploy.py to push app code + start service. ==")
    finally:
        client.close()


if __name__ == "__main__":
    main()
