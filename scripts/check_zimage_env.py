"""Check what's in ~/zimage-env and other existing venvs — can we reuse?"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    print("=== Kill any lingering pip install for our cu124 torch fetch ===")
    run(c, "pkill -f 'pip install.*pytorch.*cu124' || echo 'no proc'", check=False)

    print("\n=== ~/zimage-env Python version + packages ===")
    run(c, "~/zimage-env/bin/python --version", check=False)
    run(c, "~/zimage-env/bin/pip list 2>/dev/null | grep -iE '^(torch|torchaudio|qwen|fastapi|uvicorn|modelscope|transformers|vllm|funasr)' ", check=False)

    print("\n=== Python 3.13 user site-packages (where qwen_asr lives) ===")
    run(c, "ls ~/.local/lib/ 2>&1", check=False)
    run(c, "ls ~/.local/lib/python*/site-packages/ 2>&1 | grep -iE '(qwen|torch|fastapi|modelscope)' | head -20", check=False)

    print("\n=== test: can ~/zimage-env import qwen_asr & torch ===")
    run(c, "~/zimage-env/bin/python -c 'import torch; print(torch.__version__, torch.cuda.is_available())' 2>&1", check=False)
    run(c, "~/zimage-env/bin/python -c 'import qwen_asr; print(qwen_asr.__file__)' 2>&1", check=False)

    print("\n=== test: does python 3.13 + qwen_asr in user site work? ===")
    run(c, "ls /usr/bin/python3.13 2>&1 || echo 'no system py 3.13'", check=False)
    run(c, "which python3.13 2>&1", check=False)
    # find any python3.13
    run(c, "ls -la ~/zimage-env/bin/python* 2>&1", check=False)

    print("\n=== Free disk + free VRAM ===")
    run(c, "df -h / | tail -1", check=False)
    run(c, "nvidia-smi --query-gpu=memory.free --format=csv,noheader 2>&1", check=False)
finally:
    c.close()
