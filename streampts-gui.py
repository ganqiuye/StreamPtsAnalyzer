#!/usr/bin/env python
"""Run Stream PTS GUI without pip install (project root launcher)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from streampts.gui.launcher import main  # noqa: E402

if __name__ == "__main__":
    main()
