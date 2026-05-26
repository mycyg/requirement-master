"""Install opencode-ai globally and verify it runs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_lib import connect, run

c = connect()
try:
    print("=== Check npm ===")
    run(c, "which npm && npm --version", check=False)

    print("\n=== install opencode via curl bash (no sudo, no npm) ===")
    run(c, "curl -fsSL https://opencode.ai/install | bash 2>&1 | tail -30", check=False, timeout=300)

    print("\n=== locate the binary ===")
    run(c, "ls -la ~/.opencode/bin/ 2>&1 || ls -la ~/.local/bin/opencode 2>&1 || which opencode 2>&1", check=False)

    print("\n=== opencode help ===")
    run(c, "PATH=$HOME/.opencode/bin:$HOME/.local/bin:$PATH opencode --help 2>&1 | head -60", check=False)

    print("\n=== opencode version ===")
    run(c, "PATH=$HOME/.opencode/bin:$HOME/.local/bin:$PATH opencode --version 2>&1", check=False)
finally:
    c.close()
