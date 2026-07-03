#!/usr/bin/env python
"""Run streampts without relying on PATH entry (project root launcher)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from streampts.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
