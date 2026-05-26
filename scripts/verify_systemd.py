"""Verify all 3 systemd units are enabled (autostart) and active."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    for svc in ("yqgl-asr", "yqgl-tts", "yqgl-web"):
        print(f"\n=== {svc} ===")
        run(c, f"systemctl is-enabled {svc} 2>&1", check=False, quiet=True)
        run(c, f"systemctl is-enabled {svc}", check=False)
        run(c, f"systemctl is-active {svc}", check=False)
finally:
    c.close()
