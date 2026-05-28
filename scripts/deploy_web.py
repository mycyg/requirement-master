"""Upload web/dist/ to /srv/yqgl/web/dist/ with safe release staging."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_tree, run, sudo

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
REMOTE = "/srv/yqgl/web/dist"

if not DIST.is_dir():
    raise SystemExit(f"build first: cd web && npm run build  (missing {DIST})")

REMOTE_STAGE = REMOTE + ".new"
REMOTE_OLD = REMOTE + ".old"

c = connect()
try:
    # Atomic deploy: upload to a staging dir, then swap with the live one.
    # Previously we `rm -rf REMOTE && mkdir + put_tree`, which made the
    # web server return 404s for every asset for the 10-30s the upload
    # took — every user reloading mid-deploy saw a broken page.
    print(f"== Stage upload {DIST} → {REMOTE_STAGE} ==")
    sudo(c, f"rm -rf {REMOTE_STAGE} && mkdir -p {REMOTE_STAGE} && chown -R mycyg:mycyg /srv/yqgl/web")
    n = put_tree(c, DIST, REMOTE_STAGE)
    print(f"uploaded {n} files")

    print(f"\n== Atomic swap → {REMOTE} ==")
    # Keep the live path present even if a swap fails. New installs use a
    # release-dir symlink swap; older servers with a real dist/ directory get
    # an in-place compatibility refresh so StaticFiles never sees a missing dir.
    sudo(c, "mkdir -p /srv/yqgl/web/releases && "
            f"release=/srv/yqgl/web/releases/dist-$(date +%Y%m%d%H%M%S) && "
            f"mv {REMOTE_STAGE} \"$release\" && "
            f"if [ -L {REMOTE} ] || [ ! -e {REMOTE} ]; then "
            f"ln -sfn \"$release\" {REMOTE}.next && mv -Tf {REMOTE}.next {REMOTE}; "
            f"else mkdir -p {REMOTE} && tar -C \"$release\" -cf - . | tar -C {REMOTE} -xf -; fi && "
            "find /srv/yqgl/web/releases -maxdepth 1 -type d -name 'dist-*' "
            "-printf '%T@ %p\\n' | sort -rn | awk 'NR>5 {print $2}' | xargs -r rm -rf")
    # Clean the .old backup AFTER the swap, in case anything went wrong
    # and we need to roll back manually.
    sudo(c, f"rm -rf {REMOTE_OLD}", check=False)

    print("\n== Smoke check (no restart needed for static-only changes) ==")
    # web/dist is served by StaticFiles which reads from disk on each
    # request — no service reload needed for static-only changes.
    run(c, "curl -fsS -o /dev/null -w 'health: %{http_code}\\n' http://127.0.0.1:8080/api/health")
    run(c, "curl -fsS -o /dev/null -w 'root: %{http_code}\\n' http://127.0.0.1:8080/")
    run(c, "curl -fsS -o /dev/null -w 'spa /p/123: %{http_code}\\n' http://127.0.0.1:8080/p/123")
finally:
    c.close()
