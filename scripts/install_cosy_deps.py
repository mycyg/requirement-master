"""Install missing CosyVoice deps to py3.13 user-site (bypassing PEP 668).

Strategy: install a curated minimal subset; skip heavies (deepspeed, tensorrt, gradio,
openai-whisper). Iterate test-load to catch additional missing modules.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_text, run

PY313 = "/home/mycyg/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13"
PIP = f"{PY313} -m pip install --user --break-system-packages --no-deps"
PIP_WITH_DEPS = f"{PY313} -m pip install --user --break-system-packages"

# Curated subset of CosyVoice/requirements.txt — skipping deepspeed/tensorrt/gradio/whisper.
PACKAGES = [
    "inflect",
    "conformer",
    "librosa",
    "hydra-core",
    "omegaconf",
    "diffusers",
    "x-transformers",
    "pyworld",
    "wetext",
    "WeTextProcessing",  # commonly required by Chinese TTS
    "openai-whisper",    # included after all - cosy frontend uses it
]

PROBE = r"""
import sys, time, traceback, re
sys.path.insert(0, '/home/mycyg/CosyVoice/third_party/Matcha-TTS')
sys.path.insert(0, '/home/mycyg/CosyVoice')
try:
    from cosyvoice.cli.cosyvoice import CosyVoice3
    print('[ok] imported')
    t0 = time.time()
    m = CosyVoice3('/home/mycyg/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B')
    print(f'[ok] loaded in {time.time()-t0:.1f}s, voices={m.list_available_spks()}')
except ModuleNotFoundError as e:
    print(f'[missing] {e.name}')
except Exception as e:
    tb = traceback.format_exc()
    # scan for nested ModuleNotFoundError: No module named 'X'
    m = re.search(r"No module named '([^']+)'", tb)
    if m:
        print(f'[missing] {m.group(1)}')
    else:
        print(tb[-800:])
"""

c = connect()
try:
    print(f"=== installing {len(PACKAGES)} packages (with deps) ===")
    run(c, f"{PIP_WITH_DEPS} {' '.join(PACKAGES)} 2>&1 | tail -20", check=False, timeout=900)

    # iterate: try load, capture missing, install, repeat (max 6 rounds)
    put_text(c, "/tmp/_probe.py", PROBE)
    for i in range(6):
        print(f"\n=== probe attempt {i+1} ===")
        rc, out, _ = run(c, f"{PY313} /tmp/_probe.py 2>&1", check=False, timeout=180, quiet=False)
        if "[ok] loaded" in out:
            print("\n✅ CosyVoice loads successfully")
            break
        # find missing module
        missing = None
        for line in out.splitlines():
            if line.startswith("[missing] "):
                missing = line.split(" ", 1)[1].strip()
                break
        if not missing:
            print("no progress; aborting iteration")
            break
        print(f"  → install missing module: {missing}")
        run(c, f"{PIP_WITH_DEPS} {missing} 2>&1 | tail -10", check=False, timeout=300)
    run(c, "rm /tmp/_probe.py", check=False, quiet=True)
finally:
    c.close()
