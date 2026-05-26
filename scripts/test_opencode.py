"""Configure opencode with DeepSeek (OpenAI-compat) provider + smoke test.

Requires DEEPSEEK_API_KEY in your local env.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_text, run

KEY = os.environ.get("DEEPSEEK_API_KEY")
if not KEY:
    sys.exit("set DEEPSEEK_API_KEY in your env first")

OPENCODE_CONFIG = r"""{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "deepseek": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "DeepSeek",
      "options": {
        "baseURL": "https://api.deepseek.com/v1",
        "apiKey": "{env:DEEPSEEK_API_KEY}"
      },
      "models": {
        "deepseek-v4-pro": {
          "name": "DeepSeek V4 Pro",
          "limit": {"context": 128000, "output": 8192}
        }
      }
    }
  },
  "model": "deepseek/deepseek-v4-pro"
}
"""

c = connect()
try:
    print("=== Write ~/.config/opencode/opencode.json ===")
    run(c, "mkdir -p ~/.config/opencode", check=False, quiet=True)
    put_text(c, "/home/mycyg/.config/opencode/opencode.json", OPENCODE_CONFIG)
    run(c, "cat ~/.config/opencode/opencode.json", check=False)

    print("\n=== opencode models deepseek ===")
    run(c, f"PATH=$HOME/.opencode/bin:$PATH DEEPSEEK_API_KEY={KEY} opencode models deepseek 2>&1 | head -20", check=False)

    print("\n=== opencode run smoke (output to /tmp/oc-smoke.log) ===")
    run(c, "rm -rf /tmp/oc-smoke /tmp/oc-smoke.log && mkdir -p /tmp/oc-smoke", check=False, quiet=True)
    cmd = (
        f"cd /tmp/oc-smoke && PATH=$HOME/.opencode/bin:$PATH "
        f"DEEPSEEK_API_KEY={KEY} "
        f"timeout 300 opencode run --print-logs --log-level INFO "
        f"'在当前目录写一个名为 hello.py 的 Python 脚本，内容是 print(\"Hello YQGL!\")，只写这个文件。' "
        f"> /tmp/oc-smoke.log 2>&1; echo exit=$?"
    )
    run(c, cmd, check=False, timeout=360)

    print("\n=== /tmp/oc-smoke.log (last 80 lines) ===")
    run(c, "tail -80 /tmp/oc-smoke.log", check=False)

    print("\n=== ls of /tmp/oc-smoke ===")
    run(c, "ls -la /tmp/oc-smoke/", check=False)
    run(c, "cat /tmp/oc-smoke/hello.py 2>&1 || echo 'no hello.py'", check=False)
finally:
    c.close()
