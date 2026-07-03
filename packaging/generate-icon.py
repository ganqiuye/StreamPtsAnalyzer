"""Generate multi-resolution logo.ico for Windows desktop / exe embedding."""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "streampts" / "gui" / "assets"
SOURCE = ASSETS / "logo.png"
OUTPUT = ASSETS / "logo.ico"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _count_ico_images(path: Path) -> int:
    data = path.read_bytes()
    if len(data) < 6:
        return 0
    return struct.unpack("<HHH", data[:6])[2]


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing source image: {SOURCE}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    image = Image.open(SOURCE).convert("RGBA")
    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUTPUT,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
    )
    count = _count_ico_images(OUTPUT)
    print(f"Wrote {OUTPUT} ({count} sizes, {OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
