"""Windows shell integration for desktop shortcut icons."""

from __future__ import annotations

import sys
from pathlib import Path


def _resolve_logo_ico() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [
        exe_dir / "logo.ico",
        Path(getattr(sys, "_MEIPASS", "")) / "streampts" / "gui" / "assets" / "logo.ico",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def register_application_icon() -> None:
    """Register DefaultIcon so Windows shortcuts use logo.ico after folder move."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return

    ico = _resolve_logo_ico()
    if ico is None:
        return

    try:
        import winreg
    except ImportError:
        return

    exe_name = Path(sys.executable).name
    base = rf"Software\Classes\Applications\{exe_name}"
    icon_value = f"{ico.resolve()},0"

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as app_key:
            winreg.SetValueEx(app_key, None, 0, winreg.REG_SZ, "Stream PTS Analyzer")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\DefaultIcon") as icon_key:
            winreg.SetValueEx(icon_key, None, 0, winreg.REG_SZ, icon_value)
    except OSError:
        return
