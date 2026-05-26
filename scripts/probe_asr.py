"""Probe qwen-asr-serve install + model cache locations."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

CMDS = [
    ("which qwen-asr-serve", "binary path"),
    ("head -3 ~/.local/bin/qwen-asr-serve", "shebang/header"),
    ("~/.local/bin/qwen-asr-serve --help 2>&1 | head -30", "--help (may fail if vllm not in PATH)"),
    ("ls ~/.cache/modelscope/hub/ 2>/dev/null", "modelscope cache top"),
    ("find ~/.cache/modelscope -maxdepth 5 -type d -iname '*qwen3-asr*' 2>/dev/null", "modelscope qwen3-asr dirs"),
    ("find ~/.cache/huggingface -maxdepth 5 -type d -iname '*qwen3-asr*' 2>/dev/null", "HF cache qwen3-asr dirs"),
    ("ls ~/.cache/modelscope/hub/Qwen/Qwen3-ASR-1.7B/ 2>/dev/null", "modelscope qwen3-asr files"),
    ("python3 -c 'import vllm; print(vllm.__version__, vllm.__file__)' 2>&1 || true", "system python vllm"),
    ("pip3 show vllm qwen-asr 2>&1 | head -10", "pip3 show"),
    ("ls ~/.local/lib/python*/site-packages/ 2>&1 | grep -iE '(vllm|qwen)' | head -10", "user site-packages"),
]

c = connect()
try:
    for cmd, label in CMDS:
        print(f"\n== {label} ==")
        try:
            rc, out, err = run(c, cmd, check=False, quiet=True, timeout=20)
            print(out.rstrip() or "[empty stdout]")
            if err.strip():
                print(f"[stderr] {err.rstrip()}")
        except Exception as e:
            print(f"[error] {e}")
finally:
    c.close()
