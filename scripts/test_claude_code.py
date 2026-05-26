"""Test Claude Code (the already-installed `claude` CLI) as the agent backend, pointed at DeepSeek.

Requires DEEPSEEK_API_KEY in your local env.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

KEY = os.environ.get("DEEPSEEK_API_KEY")
if not KEY:
    sys.exit("set DEEPSEEK_API_KEY in your env first")

c = connect()
try:
    print("=== claude version ===")
    run(c, "claude --version 2>&1 | head -3", check=False)

    print("\n=== claude -p with DeepSeek (Anthropic-compat) ===")
    run(c, "rm -rf /tmp/cc-smoke /tmp/cc-smoke.log && mkdir -p /tmp/cc-smoke", check=False, quiet=True)
    cmd = (
        f"cd /tmp/cc-smoke && "
        f"ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic "
        f"ANTHROPIC_API_KEY={KEY} "
        f"ANTHROPIC_AUTH_TOKEN={KEY} "
        "ANTHROPIC_MODEL=deepseek-v4-pro "
        "ANTHROPIC_SMALL_FAST_MODEL=deepseek-v4-flash "
        "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro "
        "ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro "
        "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash "
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 "
        "timeout 180 claude -p --dangerously-skip-permissions "
        "'写一个 hello.py，内容 print(\"Hello YQGL!\")。只写这个文件。' "
        "< /dev/null > /tmp/cc-smoke.log 2>&1 ; echo exit=$?"
    )
    run(c, cmd, check=False, timeout=240)

    print("\n=== /tmp/cc-smoke.log ===")
    run(c, "cat /tmp/cc-smoke.log | head -60", check=False)
    print("\n=== ls of /tmp/cc-smoke ===")
    run(c, "ls -la /tmp/cc-smoke/", check=False)
    run(c, "cat /tmp/cc-smoke/hello.py 2>&1 || echo 'no hello.py'", check=False)
    run(c, "python3 /tmp/cc-smoke/hello.py 2>&1 || echo 'cannot run'", check=False)
finally:
    c.close()
