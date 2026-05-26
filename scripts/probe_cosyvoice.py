"""Probe CosyVoice: list voices, test load, generate a 1-line sample."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, put_text, run

PY313 = "/home/mycyg/.local/share/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13"

TEST = r"""
import sys, os, time
sys.path.insert(0, '/home/mycyg/CosyVoice/third_party/Matcha-TTS')
sys.path.insert(0, '/home/mycyg/CosyVoice')

try:
    from cosyvoice.cli.cosyvoice import CosyVoice3
    print("[ok] import CosyVoice3")
except Exception as e:
    print(f"[fail] import CosyVoice3: {type(e).__name__}: {e}")
    sys.exit(1)

MODEL = '/home/mycyg/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B'
print(f"loading {MODEL} ...")
t0 = time.time()
try:
    m = CosyVoice3(MODEL)
    print(f"[ok] loaded in {time.time()-t0:.1f}s")
except Exception as e:
    print(f"[fail] CosyVoice3() init: {type(e).__name__}: {e}")
    sys.exit(1)

try:
    voices = m.list_available_spks()
    print(f"available speakers: {voices}")
except Exception as e:
    print(f"[fail] list_available_spks: {e}")

# Try a quick inference
import soundfile as sf
import io
try:
    print("generating 1 line ...")
    t0 = time.time()
    if voices:
        for i, res in enumerate(m.inference_zero_shot('你好，欢迎使用需求管理大师。', '', '', zero_shot_spk_id=voices[0], stream=False)):
            data = res['tts_speech'].cpu().numpy().squeeze()
            print(f"  chunk {i}: shape={data.shape} sr=22050")
            buf = io.BytesIO()
            sf.write(buf, data, 22050, format='WAV')
            print(f"  WAV bytes: {len(buf.getvalue())}")
            break
        print(f"[ok] inference in {time.time()-t0:.1f}s")
    else:
        print("[skip] no zero_shot speakers available; try cross_lingual or other API")
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"[fail] inference: {type(e).__name__}: {e}")
"""

c = connect()
try:
    put_text(c, "/tmp/_probe_cosy.py", TEST)
    print(f"running probe with {PY313} ...")
    run(c, f"{PY313} /tmp/_probe_cosy.py 2>&1", check=False, timeout=180)
    run(c, "rm /tmp/_probe_cosy.py", check=False, quiet=True)
finally:
    c.close()
