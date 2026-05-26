"""Install ALL Python deps needed by both ASR (qwen_asr) and TTS (CosyVoice3).

Targets Python 3.13 installed via uv. Installs to user-site with
`pip install --user --break-system-packages` (uv-managed pythons are PEP 668 externally-managed).

What gets installed:
  - torch + torchaudio (CUDA 12.4 wheels from official pytorch index)
  - qwen-asr (for the ASR service)
  - cosyvoice runtime deps (curated subset of CosyVoice/requirements.txt — skips deepspeed/
    tensorrt/gradio/openai-whisper-full; includes inflect/conformer/librosa/diffusers/rich/etc.)
  - fastapi + uvicorn + python-multipart + soundfile

Then probes that CosyVoice3 loads end-to-end; if missing modules surface, installs them iteratively.

First run takes 10-15 minutes (torch download). Subsequent runs are mostly no-ops.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_text, run

CUDA_WHEEL = "https://download.pytorch.org/whl/cu124"

CORE_PACKAGES = [
    "fastapi", "uvicorn[standard]", "python-multipart",
    "soundfile", "numpy",
    "qwen-asr",
]

COSY_PACKAGES = [
    "HyperPyYAML", "inflect", "conformer", "librosa", "hydra-core", "omegaconf",
    "diffusers", "x-transformers", "pyworld", "wetext", "onnxruntime",
    "rich", "modelscope", "transformers",
]

PROBE = r"""
import sys, time, traceback, re, os
HOME = os.path.expanduser("~")
sys.path.insert(0, f"{HOME}/CosyVoice/third_party/Matcha-TTS")
sys.path.insert(0, f"{HOME}/CosyVoice")
try:
    from cosyvoice.cli.cosyvoice import CosyVoice3
    print('[ok] imported')
    model_dir = f"{HOME}/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B"
    if not os.path.isdir(model_dir):
        print(f'[skip] model dir missing: {model_dir} (run download_models.py first)')
        sys.exit(0)
    t0 = time.time()
    m = CosyVoice3(model_dir)
    print(f'[ok] loaded in {time.time()-t0:.1f}s, voices={m.list_available_spks()}')
except ModuleNotFoundError as e:
    print(f'[missing] {e.name}')
except Exception as e:
    tb = traceback.format_exc()
    m = re.search(r"No module named '([^']+)'", tb)
    if m:
        print(f'[missing] {m.group(1)}')
    else:
        print(tb[-800:])
"""


def main() -> None:
    c = connect()
    try:
        rc, out, _ = run(c, "~/.local/bin/uv python find 3.13 2>/dev/null || echo MISSING",
                          check=False, quiet=True)
        py = out.strip().splitlines()[-1] if out.strip() else "MISSING"
        if "MISSING" in py:
            sys.exit("Python 3.13 not installed; run scripts/setup_py313.py first")
        pip_install = f"{py} -m pip install --user --break-system-packages"

        print(f"py3.13: {py}")

        print("\n== 1. torch + torchaudio (CUDA 12.4 wheels) ==")
        rc, _, _ = run(c, f"{py} -c 'import torch; print(torch.cuda.is_available())' 2>&1",
                        check=False, quiet=True)
        if rc == 0:
            print("  ✓ torch already installed")
        else:
            run(c, f"{pip_install} --index-url {CUDA_WHEEL} torch torchaudio", timeout=1200)

        print("\n== 2. Core API packages (fastapi/uvicorn/qwen-asr/...) ==")
        run(c, f"{pip_install} {' '.join(CORE_PACKAGES)} 2>&1 | tail -10",
            check=False, timeout=600)

        print("\n== 3. CosyVoice deps (curated subset) ==")
        run(c, f"{pip_install} {' '.join(COSY_PACKAGES)} 2>&1 | tail -10",
            check=False, timeout=900)

        print("\n== 4. Iteratively probe CosyVoice load (fill in missing modules) ==")
        put_text(c, "/tmp/_probe.py", PROBE)
        for i in range(6):
            print(f"\n  attempt {i+1}")
            rc, out, _ = run(c, f"{py} /tmp/_probe.py 2>&1", check=False,
                              timeout=180, quiet=False)
            if "[ok] loaded" in out or "[skip]" in out:
                print("  ✅ Python deps look good")
                break
            missing = None
            for line in out.splitlines():
                if line.startswith("[missing] "):
                    missing = line.split(" ", 1)[1].strip()
                    break
            if not missing:
                print("  no progress; aborting iteration (check log above)")
                break
            print(f"  → install missing module: {missing}")
            run(c, f"{pip_install} {missing} 2>&1 | tail -5", check=False, timeout=300)
        run(c, "rm /tmp/_probe.py", check=False, quiet=True)

        print("\n✅ Done. Next: scripts/provision_asr.py + scripts/provision_tts.py")
    finally:
        c.close()


if __name__ == "__main__":
    main()
