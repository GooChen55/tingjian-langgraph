"""Set local import paths for directly executed maintenance scripts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in ("shared", "assistant", "knowledge", "operations", "workers"):
    sys.path.insert(0, str(ROOT / "python" / folder))
