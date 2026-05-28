import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, sudo, run

c = connect()
try:
    for svc in ("yqgl-web", "yqgl-asr", "yqgl-tts"):
        sudo(c, f"systemctl restart {svc}", check=False)
    run(c, "sleep 12 && systemctl is-active yqgl-asr yqgl-tts yqgl-web", check=False)
    run(c, "curl -s http://127.0.0.1:8001/health | head -c 200", check=False)
    print()
    run(c, "curl -s http://127.0.0.1:8002/health | head -c 200", check=False)
    print()
    print("=== last 30 lines asr ===")
    run(c, "tail -30 /srv/yqgl/data/asr.log", check=False)
    print("=== last 30 lines tts ===")
    run(c, "tail -30 /srv/yqgl/data/tts.log", check=False)
finally:
    c.close()
