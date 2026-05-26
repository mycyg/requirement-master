import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    run(c, "ls -la /srv/yqgl/data/deliveries/ 2>&1 | tail -5", check=False)
    run(c, "find /srv/yqgl/data/deliveries/ -name '*.zip' -newer /tmp -mmin -10 2>&1 | head -3", check=False)
    run(c, "ls -la /srv/yqgl/data/deliveries/*/ 2>&1 | tail -10", check=False)
    print("\n=== unzip latest + show content ===")
    run(c, "Z=$(find /srv/yqgl/data/deliveries/ -name '*.zip' -mmin -10 | tail -1); echo zip: $Z && unzip -p \"$Z\" fizzbuzz.py | head -40", check=False)
    print("\n=== SQLite query ===")
    run(c, "/srv/yqgl/venv/bin/python -c \"from sqlalchemy import create_engine, text; e=create_engine('sqlite:////srv/yqgl/data/yqgl.db'); c=e.connect(); rows=c.execute(text('SELECT round, file_count, submitted_by_nickname, length(delivery_doc_md) as doc_len FROM deliveries ORDER BY created_at DESC LIMIT 3')).fetchall(); [print(dict(r._mapping)) for r in rows]\"", check=False)
finally:
    c.close()
