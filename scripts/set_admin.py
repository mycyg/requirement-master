"""Grant or revoke admin on a yqgl user by nickname.

Usage:
    python scripts/set_admin.py 小光                  # grant
    python scripts/set_admin.py 小光 --revoke         # revoke
    python scripts/set_admin.py --list                # show current admins

When ``--bootstrap`` is passed (or ``YQGL_BOOTSTRAP_NICKNAMES`` is set), the
user row is created if it doesn't exist yet (cookie_token left empty — the
user finishes login on first identify).

Run inside the same venv that runs uvicorn so the DATABASE_URL setting resolves
to the prod DB.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

# Make `app/` importable without installing.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "app"))

from db import SessionLocal, engine  # noqa: E402
from models import Base, User  # noqa: E402
from services.schema_migrations import ensure_runtime_schema  # noqa: E402


def make_token() -> str:
    return secrets.token_urlsafe(32)


def grant(nickname: str, *, revoke: bool, bootstrap: bool) -> int:
    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)

    with SessionLocal() as db:
        user = db.query(User).filter(User.nickname == nickname).first()
        if not user:
            if not bootstrap:
                print(f"[!] user '{nickname}' does not exist. "
                      f"Either let them log in first, or re-run with --bootstrap to seed.")
                return 1
            user = User(nickname=nickname, cookie_token=make_token())
            db.add(user)
            db.flush()
            print(f"[+] bootstrapped user '{nickname}' (id={user.id})")

        before = bool(getattr(user, "is_admin", False))
        user.is_admin = not revoke
        db.commit()
        after = bool(getattr(user, "is_admin", False))
        action = "revoked" if revoke else "granted"
        if before == after:
            print(f"[=] '{nickname}' is_admin already {after}; nothing to change.")
        else:
            print(f"[+] {action} admin on '{nickname}'  (was={before} → now={after})")
        return 0


def list_admins() -> int:
    Base.metadata.create_all(engine)
    ensure_runtime_schema(engine)
    with SessionLocal() as db:
        admins = db.query(User).filter(User.is_admin.is_(True)).order_by(User.nickname).all()
        if not admins:
            print("(no admins)")
            return 0
        print("Admins:")
        for u in admins:
            print(f"  - {u.nickname}  (id={u.id})")
        return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Manage yqgl admin flag.")
    p.add_argument("nickname", nargs="?", help="Nickname to flip.")
    p.add_argument("--revoke", action="store_true", help="Remove admin instead of granting.")
    p.add_argument("--bootstrap", action="store_true",
                   help="Create the user row if it doesn't exist (cookie_token randomly seeded).")
    p.add_argument("--list", action="store_true", help="List current admins and exit.")
    args = p.parse_args(argv)

    # Env-driven bootstrap convenience.
    if not args.nickname and not args.list:
        env = os.environ.get("YQGL_BOOTSTRAP_NICKNAMES", "").strip()
        if env:
            rc = 0
            for nick in [n.strip() for n in env.split(",") if n.strip()]:
                rc |= grant(nick, revoke=False, bootstrap=True)
            return rc
        p.print_help()
        return 2

    if args.list:
        return list_admins()
    return grant(args.nickname, revoke=args.revoke, bootstrap=args.bootstrap)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
