"""Deploy app/ and client/ to /srv/yqgl on the server and restart yqgl-web.

Usage:
  python scripts/deploy.py             # deploy app + restart web
  python scripts/deploy.py --no-restart
  python scripts/deploy.py --env       # also upload app/.env (must exist locally)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ssh_lib import connect, put_file, put_tree, run, sudo  # noqa: E402


REMOTE_APP = "/srv/yqgl/app"
REMOTE_CLIENT = "/srv/yqgl/client"
EXCLUDE = {"__pycache__", ".pytest_cache", ".venv", "venv", ".env"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--env", action="store_true", help="Also upload local app/.env")
    args = parser.parse_args()

    client = connect()
    try:
        print(f"== Uploading app/ → {REMOTE_APP} ==")
        local_app = ROOT / "app"
        if not local_app.exists():
            raise SystemExit(f"local {local_app} does not exist")
        n = put_tree(client, local_app, REMOTE_APP, exclude=EXCLUDE)
        print(f"uploaded {n} files")

        print(f"\n== Uploading client/ → {REMOTE_CLIENT} ==")
        local_client = ROOT / "client"
        if not local_client.exists():
            raise SystemExit(f"local {local_client} does not exist")
        sudo(client, f"mkdir -p {REMOTE_CLIENT} && chown -R mycyg:mycyg {REMOTE_CLIENT}")
        n = put_tree(client, local_client, REMOTE_CLIENT, exclude=EXCLUDE)
        print(f"uploaded {n} client files")

        if args.env:
            env_local = local_app / ".env"
            if not env_local.exists():
                raise SystemExit("app/.env not found locally; create it from .env.example")
            put_file(client, env_local, f"{REMOTE_APP}/.env", mode=0o600)
            print("uploaded app/.env (mode 600)")

        if not args.no_restart:
            print("\n== Restarting yqgl-web ==")
            sudo(client, "systemctl restart yqgl-web.service")
            run(client, "sleep 1 && curl -sS http://127.0.0.1:8080/api/health")
    finally:
        client.close()


if __name__ == "__main__":
    main()
