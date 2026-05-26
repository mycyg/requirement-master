"""Install Python 3.13 via uv and verify it picks up ~/.local/lib/python3.13/site-packages."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    print("=== Configure pip to use Tsinghua mirror (system-wide for mycyg) ===")
    run(c, "mkdir -p ~/.config/pip && cat > ~/.config/pip/pip.conf <<'EOF'\n[global]\nindex-url = https://pypi.tuna.tsinghua.edu.cn/simple/\nextra-index-url = https://mirrors.aliyun.com/pypi/simple/\ntrusted-host = pypi.tuna.tsinghua.edu.cn mirrors.aliyun.com\nEOF\ncat ~/.config/pip/pip.conf", check=False)

    print("\n=== Install Python 3.13 via uv (~30 MB, fast) ===")
    run(c, "~/.local/bin/uv python install 3.13", timeout=180)

    print("\n=== Locate installed 3.13 binary ===")
    rc, out, _ = run(c, "~/.local/bin/uv python find 3.13", check=False)
    py313 = out.strip().splitlines()[-1] if out.strip() else ""
    print(f"py313 = {py313!r}")
    if not py313:
        print("✗ couldn't find py3.13"); raise SystemExit(1)

    print("\n=== Probe: can it import torch, qwen_asr, fastapi from user-site ===")
    run(c, f"{py313} -c 'import torch; print(\"torch\", torch.__version__, \"cuda:\", torch.cuda.is_available())'", check=False)
    run(c, f"{py313} -c 'import qwen_asr; print(\"qwen_asr from\", qwen_asr.__file__)'", check=False)
    run(c, f"{py313} -c 'import fastapi, uvicorn, multipart; print(\"fastapi\", fastapi.__version__, \"uvicorn\", uvicorn.__version__)'", check=False)

    print("\n=== List what else is in user-site that we might want ===")
    run(c, "ls ~/.local/lib/python3.13/site-packages/ | wc -l", check=False)
    run(c, "ls ~/.local/lib/python3.13/site-packages/ | grep -iE '^(uvicorn|starlette|httptools|websockets|python_multipart|multipart|httpx|h11)' ", check=False)

    # Write the resolved python path to a known file for the provision script
    run(c, f"echo {py313} > /tmp/yqgl_py313_path", check=False, quiet=True)
    print(f"\nSaved py3.13 path to /tmp/yqgl_py313_path")
finally:
    c.close()
