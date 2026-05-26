"""Update opencode model limits to match DeepSeek v4 Pro (900k context, 128k output)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_text, run

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
          "limit": {"context": 900000, "output": 128000}
        },
        "deepseek-v4-flash": {
          "name": "DeepSeek V4 Flash",
          "limit": {"context": 900000, "output": 128000}
        }
      }
    }
  },
  "model": "deepseek/deepseek-v4-pro",
  "small_model": "deepseek/deepseek-v4-flash"
}
"""

c = connect()
try:
    put_text(c, "/home/mycyg/.config/opencode/opencode.json", OPENCODE_CONFIG)
    run(c, "cat ~/.config/opencode/opencode.json", check=False)
finally:
    c.close()
