"""Re-embed application icon into the built exe using rcedit.

WARNING: rcedit can corrupt PyInstaller onedir bootloaders and cause
'Cannot load PyInstaller''s embedded PKG archive'. Do not use in build-gui.bat.
PyInstaller --icon in the spec file is the safe approach for onedir builds.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

RCEDIT_VERSION = "2.0.0"
RCEDIT_URL = (
    f"https://github.com/electron/rcedit/releases/download/v{RCEDIT_VERSION}/rcedit-x64.exe"
)


def _rcedit_path() -> Path:
    tools = Path(__file__).resolve().parent / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    exe = tools / "rcedit.exe"
    if exe.is_file():
        return exe
    print(f"Downloading rcedit from {RCEDIT_URL} ...")
    urllib.request.urlretrieve(RCEDIT_URL, exe)  # noqa: S310
    return exe


def embed_icon(exe_path: Path, icon_path: Path) -> None:
    if not exe_path.is_file():
        raise SystemExit(f"Executable not found: {exe_path}")
    if not icon_path.is_file():
        raise SystemExit(f"Icon not found: {icon_path}")

    rcedit = _rcedit_path()
    proc = subprocess.run(
        [str(rcedit), str(exe_path), "--set-icon", str(icon_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"rcedit failed ({proc.returncode}): {detail}")
    print(f"Embedded icon into {exe_path}")


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        raise SystemExit("Usage: embed-exe-icon.py <exe-path> <ico-path>")
    embed_icon(Path(args[0]), Path(args[1]))


if __name__ == "__main__":
    main()
