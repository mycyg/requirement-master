"""Upload web/dist/ to /srv/yqgl/web/dist/ and restart yqgl-web."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_tree, run, sudo

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
REMOTE = "/srv/yqgl/web/dist"

if not DIST.is_dir():
    raise SystemExit(f"build first: cd web && npm run build  (missing {DIST})")

c = connect()
try:
    print(f"== Clean + upload {DIST} → {REMOTE} ==")
    sudo(c, f"rm -rf {REMOTE} && mkdir -p {REMOTE} && chown -R mycyg:mycyg /srv/yqgl/web")
    n = put_tree(c, DIST, REMOTE)
    print(f"uploaded {n} files")

    print("\n== Restart yqgl-web ==")
    sudo(c, "systemctl restart yqgl-web.service")
    run(c, "sleep 1 && curl -sS -o /dev/null -w 'health: %{http_code}\\n' http://127.0.0.1:8080/api/health", check=False)
    run(c, "curl -sS -o /dev/null -w 'root: %{http_code}\\n' http://127.0.0.1:8080/", check=False)
    run(c, "curl -sS -o /dev/null -w 'spa /p/123: %{http_code}\\n' http://127.0.0.1:8080/p/123", check=False)
finally:
    c.close()
