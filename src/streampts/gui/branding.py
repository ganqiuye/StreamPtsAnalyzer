from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        bundled = base / "streampts" / "gui" / "assets"
        if bundled.is_dir():
            return bundled
    return Path(__file__).resolve().parent / "assets"


def asset_path(name: str) -> Path:
    return assets_dir() / name


def has_logo() -> bool:
    return asset_path("logo.png").is_file()
