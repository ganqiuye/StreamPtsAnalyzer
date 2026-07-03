from __future__ import annotations

from streampts.models import UnitName


def pts_us_from_time(pts_time: float) -> int:
    """Display µs as integer from ffprobe pts_time (seconds)."""
    return int(round(pts_time * 1_000_000))


def pts_to_unit(pts: int, pts_time: float, unit: UnitName) -> float:
    if unit == "90k":
        return float(pts)
    if unit == "us":
        return float(pts_us_from_time(pts_time))
    if unit == "ms":
        return pts_time * 1_000
    return pts_time


def pts_display_text(pts: int, pts_time: float, unit: UnitName) -> str:
    if unit == "90k":
        return str(pts)
    if unit == "us":
        return str(pts_us_from_time(pts_time))
    if unit == "ms":
        return f"{pts_time * 1000:.3f}"
    return f"{pts_time:.6f}"


def unit_label(unit: UnitName) -> str:
    return {"90k": "PTS (90k)", "us": "PTS (µs)", "ms": "ms", "sec": "s"}[unit]


def format_time(seconds: float) -> str:
    if seconds < 0:
        return f"-{format_time(-seconds)}"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


def ms_from_pts_delta(delta_pts: int) -> float:
    return delta_pts / 90.0
