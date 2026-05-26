"""Sanity-check the DeepSeek (Anthropic-compatible) endpoint.

Sends a small messages.create request from the server (which already has anthropic SDK installed
in /srv/yqgl/venv). Prints raw and parsed response.

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

PY = "/srv/yqgl/venv/bin/python"

TEST = r"""
import json, os
from anthropic import Anthropic

c = Anthropic(
    base_url="https://api.deepseek.com/anthropic",
    api_key=os.environ["DEEPSEEK_API_KEY"],
)

# 1. Try the user-provided model name first
for model_name in ["eepseek-v4-pro", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]:
    print(f"\n=== trying model: {model_name} ===")
    try:
        msg = c.messages.create(
            model=model_name,
            max_tokens=200,
            system="Reply with valid JSON only: {\"action\":\"ping\",\"ok\":true,\"echo\":<input>}",
            messages=[{"role": "user", "content": "say hi"}],
        )
        print("OK")
        print("model_used:", msg.model)
        print("stop_reason:", msg.stop_reason)
        print("content:", msg.content)
        if msg.content and hasattr(msg.content[0], "text"):
            print("text:", msg.content[0].text[:500])
        break
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {str(e)[:300]}")
"""

c = connect()
try:
    # write via a here-doc-like file upload
    run(c, f"cat > /tmp/_test_llm.py <<'PYEOF'\n{TEST}\nPYEOF", check=True, quiet=True)
    run(c, f"DEEPSEEK_API_KEY={KEY} {PY} /tmp/_test_llm.py", check=False, timeout=60)
    run(c, "rm /tmp/_test_llm.py", check=False, quiet=True)
finally:
    c.close()
