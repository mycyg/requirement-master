"""Wait for ASR /health to be ready, then transcribe a known-good wav."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

TEST_WAV = "/home/mycyg/asr_work/chunks/chunk_0000.wav"


def main() -> None:
    c = connect()
    try:
        print("== Wait for /health ready (timeout 180s) ==")
        for i in range(36):
            rc, out, _ = run(c, "curl -s -m 3 http://127.0.0.1:8001/health", check=False, quiet=True)
            print(f"  t={i*5:>3}s  {out.strip()[:200]}")
            if '"ready":true' in out or '"ready": true' in out:
                print("ready!")
                break
            time.sleep(5)
        else:
            print("[fail] model not ready after 180s; tail of log:")
            run(c, "tail -50 /srv/yqgl/data/asr.log", check=False)
            sys.exit(1)

        print("\n== Transcribe test wav ==")
        rc, out, err = run(
            c,
            f"curl -s -m 60 -X POST -F 'audio=@{TEST_WAV}' http://127.0.0.1:8001/transcribe",
            check=False,
        )
        print(out)
        if err.strip():
            print(f"[stderr] {err}")
    finally:
        c.close()


if __name__ == "__main__":
    main()
