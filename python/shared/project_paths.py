"""Stable project paths, independent of the current working directory."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime" / "vm" if os.environ.get("LISTENING_INFRASTRUCTURE") == "vm" else ROOT / ".runtime"
