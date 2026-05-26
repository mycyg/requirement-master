import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    run(c, "tail -80 /srv/yqgl/data/web.log", check=False)
finally:
    c.close()
