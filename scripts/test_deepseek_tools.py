"""Probe whether DeepSeek (Anthropic-compat) supports Anthropic-style tool_use.

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

TEST = r"""
import os, json
from anthropic import Anthropic

c = Anthropic(
    base_url="https://api.deepseek.com/anthropic",
    api_key=os.environ["DEEPSEEK_API_KEY"],
)

tools = [
    {
        "name": "write_file",
        "description": "Write text content to a file path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "submit",
        "description": "Call this when the task is complete.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

try:
    msg = c.messages.create(
        model="deepseek-v4-pro",
        max_tokens=4096,
        system="你是一个程序员。用 write_file 工具创建用户要求的文件，完成后调用 submit。",
        tools=tools,
        messages=[{"role": "user", "content": "在当前目录写 hello.py，内容是 print('Hello YQGL!')。"}],
    )
    print("OK; stop_reason:", msg.stop_reason)
    for block in msg.content:
        print(f"  block type={block.type}")
        if block.type == "tool_use":
            print(f"    tool={block.name}  input={block.input}")
        elif block.type == "text":
            print(f"    text={block.text[:200]!r}")
        elif block.type == "thinking":
            print(f"    thinking={block.thinking[:120]!r}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
"""

c = connect()
try:
    put_text(c, "/tmp/_test_tools.py", TEST)
    run(c, f"DEEPSEEK_API_KEY={KEY} /srv/yqgl/venv/bin/python /tmp/_test_tools.py 2>&1", check=False, timeout=60)
    run(c, "rm /tmp/_test_tools.py", check=False, quiet=True)
finally:
    c.close()
