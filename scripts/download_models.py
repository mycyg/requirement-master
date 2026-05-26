"""One-time: download Qwen3-ASR-1.7B + clone CosyVoice + download Fun-CosyVoice3-0.5B.

Idempotent. Runs against the SSH target in scripts/server_creds.py.

Models cached at:
  Qwen3-ASR:  ~/.cache/modelscope/hub/models/Qwen/Qwen3-ASR-1___7B (~4.7 GB)
  CosyVoice:  ~/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B (~2 GB)

Total download: ~7 GB on first run. Subsequent runs are no-ops.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

PY313 = "/home/USERNAME_PLACEHOLDER/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13"


def main() -> None:
    c = connect()
    try:
        # Find py3.13 first (resolves USERNAME_PLACEHOLDER properly)
        rc, out, _ = run(c, "~/.local/bin/uv python find 3.13 2>/dev/null || echo MISSING", check=False, quiet=True)
        py = out.strip().splitlines()[-1] if out.strip() else "MISSING"
        if "MISSING" in py:
            sys.exit("Python 3.13 not installed; run scripts/setup_py313.py first")
        print(f"py3.13: {py}")

        print("\n== 1. modelscope CLI (used to fetch ASR model) ==")
        rc, _, _ = run(c, f"{py} -c 'import modelscope' 2>&1", check=False, quiet=True)
        if rc != 0:
            run(c, f"{py} -m pip install --user --break-system-packages modelscope", timeout=300)

        print("\n== 2. Download Qwen3-ASR-1.7B (~4.7 GB; skips if already cached) ==")
        ASR_DIR = "~/.cache/modelscope/hub/models/Qwen/Qwen3-ASR-1___7B"
        rc, _, _ = run(c, f"test -d {ASR_DIR}", check=False, quiet=True)
        if rc == 0:
            print(f"  ✓ already at {ASR_DIR}")
        else:
            print(f"  downloading…")
            run(c, f"{py} -c \"from modelscope import snapshot_download; "
                   f"p = snapshot_download('Qwen/Qwen3-ASR-1.7B'); print('saved at', p)\"",
                timeout=1800)

        print("\n== 3. Clone CosyVoice repo (if missing) ==")
        rc, _, _ = run(c, "test -d ~/CosyVoice/.git", check=False, quiet=True)
        if rc == 0:
            print("  ✓ ~/CosyVoice already exists")
            run(c, "cd ~/CosyVoice && git pull --recurse-submodules 2>&1 | tail -3", check=False)
        else:
            print("  cloning (with submodules — Matcha-TTS is a submodule)…")
            run(c, "cd ~ && git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git", timeout=600)

        print("\n== 4. Download Fun-CosyVoice3-0.5B model (~2 GB) ==")
        COSY_MODEL = "~/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B"
        rc, _, _ = run(c, f"test -d {COSY_MODEL}", check=False, quiet=True)
        if rc == 0:
            print(f"  ✓ already at {COSY_MODEL}")
        else:
            print(f"  downloading…")
            run(c, f"{py} -c \"from modelscope import snapshot_download; "
                   f"p = snapshot_download('iic/CosyVoice3-0.5B', cache_dir='~/CosyVoice/pretrained_models'); "
                   f"print('saved at', p)\"",
                timeout=1800)
            # Some forks expect dir named 'Fun-CosyVoice3-0.5B'; symlink if needed
            run(c, "cd ~/CosyVoice/pretrained_models && "
                  "([ -d Fun-CosyVoice3-0.5B ] || ln -s iic/CosyVoice3-0.5B Fun-CosyVoice3-0.5B) 2>&1",
                check=False)

        print("\n✅ Models ready. Next: scripts/install_cosy_deps.py to install Python deps.")
    finally:
        c.close()


if __name__ == "__main__":
    main()
