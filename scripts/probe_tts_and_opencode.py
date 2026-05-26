import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    print("=== CosyVoice repo & pretrained_models ===")
    run(c, "ls ~/CosyVoice/pretrained_models/ 2>&1", check=False)
    run(c, "find ~/CosyVoice/pretrained_models -maxdepth 2 -type d 2>&1 | head -20", check=False)
    run(c, "ls ~/CosyVoice/*.json ~/CosyVoice/*.txt ~/CosyVoice/*.wav ~/CosyVoice/*.mp3 2>&1", check=False)
    run(c, "head -20 ~/CosyVoice/男-参考.json 2>&1", check=False)
    run(c, "head -10 ~/CosyVoice/男-参考.txt 2>&1", check=False)
    run(c, "cat ~/CosyVoice/参考3.txt 2>&1", check=False)
    run(c, "ls -la ~/CosyVoice/asset/ 2>&1 | head -10", check=False)

    print("\n=== CosyVoice can be imported via py3.13 user-site? ===")
    run(c, "ls ~/.local/lib/python3.13/site-packages/ | grep -iE '(cosy|hyperpyyaml|onnx)' | head -20", check=False)

    print("\n=== Reference scripts the user wrote ===")
    run(c, "head -50 ~/CosyVoice/hermes_tts.py 2>&1", check=False)

    print("\n=== opencode binary on server? ===")
    run(c, "which opencode 2>&1 || echo 'not found'", check=False)
    run(c, "ls ~/.local/bin/opencode 2>&1 || echo 'not in ~/.local/bin'", check=False)
    run(c, "npm list -g --depth=0 2>/dev/null | grep -i opencode || echo 'not in npm global'", check=False)
    run(c, "which claude && claude --version 2>&1 | head -3 || echo 'no claude code'", check=False)
    # alternative: hermes-agent (we saw it in user's bash_history)
    run(c, "which hermes && hermes --version 2>&1 | head -3 || echo 'no hermes'", check=False)
finally:
    c.close()
