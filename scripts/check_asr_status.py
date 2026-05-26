import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    run(c, "ps aux | grep -E '(pip|provision)' | grep -v grep || echo 'no pip/provision proc'", check=False)
    run(c, "ls -la /srv/yqgl/asr-venv/lib/python3.12/site-packages/ | head -30", check=False)
    run(c, "du -sh /srv/yqgl/asr-venv 2>/dev/null", check=False)
    run(c, "ls /srv/yqgl/asr_service/ 2>/dev/null", check=False)
    run(c, "systemctl status yqgl-asr.service --no-pager 2>&1 | head -25", check=False)
    run(c, "ls -la /etc/systemd/system/yqgl-asr.service 2>/dev/null", check=False)
finally:
    c.close()
