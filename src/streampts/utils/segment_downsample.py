from __future__ import annotations

import numpy as np

from streampts.models import PcrPoint, SeriesPoint
from streampts.utils.downsample import lttb_downsample
from streampts.utils.timeline import (
    continuous_times_for_pcr,
    continuous_times_for_points,
    has_timeline_resets,
    iter_pcr_segments,
    iter_series_segments,
    ordered_pts_times,
)


def _segment_budgets(segment_sizes: list[int], max_points: int) -> list[int]:
    if not segment_sizes:
        return []
    if max_points <= 0:
        return [0] * len(segment_sizes)
    if max_points >= sum(segment_sizes):
        return segment_sizes[:]

    n = len(segment_sizes)
    min_each = 2 if max_points >= 2 * n else 1
    budgets = [min_each if max_points >= min_each * n else 1] * n
    remaining = max_points - sum(budgets)
    total = sum(segment_sizes)

    if remaining <= 0:
        return [min(b, s) for b, s in zip(budgets, segment_sizes)]

    extras = [0] * n
    fractional: list[tuple[float, int]] = []
    for i, size in enumerate(segment_sizes):
        share = remaining * size / total
        whole = int(share)
        extras[i] = whole
        fractional.append((share - whole, i))

    used = sum(extras)
    leftover = remaining - used
    for _, idx in sorted(fractional, reverse=True):
        if leftover <= 0:
            break
        extras[idx] += 1
        leftover -= 1

    return [
        min(size, base + extra)
        for size, base, extra in zip(segment_sizes, budgets, extras)
    ]


def _downsample_ordered_series(
    ordered: list[SeriesPoint],
    max_points: int,
) -> list[SeriesPoint]:
    if len(ordered) <= max_points:
        return ordered
    timeline_x = continuous_times_for_points(ordered)
    x = np.array(timeline_x, dtype=float)
    y = np.array([float(p.pts) for p in ordered], dtype=float)
    sx, _ = lttb_downsample(x, y, max_points)
    picked: list[int] = []
    seen: set[int] = set()
    for tx in sx:
        idx = int(np.argmin(np.abs(x - tx)))
        if idx not in seen:
            seen.add(idx)
            picked.append(idx)
    if 0 not in picked:
        picked.append(0)
    if len(ordered) - 1 not in picked:
        picked.append(len(ordered) - 1)
    picked = sorted(set(picked))
    if len(picked) > max_points:
        picked = picked[: max_points - 1] + [len(ordered) - 1]
    return [ordered[i] for i in picked]


def _downsample_ordered_pcr(
    ordered: list[PcrPoint],
    max_points: int,
) -> list[PcrPoint]:
    if len(ordered) <= max_points:
        return ordered
    timeline_x = continuous_times_for_pcr(ordered)
    x = np.array(timeline_x, dtype=float)
    y = np.array([float(p.pcr or 0) for p in ordered], dtype=float)
    sx, _ = lttb_downsample(x, y, max_points)
    picked: list[int] = []
    seen: set[int] = set()
    for tx in sx:
        idx = int(np.argmin(np.abs(x - tx)))
        if idx not in seen:
            seen.add(idx)
            picked.append(idx)
    if 0 not in picked:
        picked.append(0)
    if len(ordered) - 1 not in picked:
        picked.append(len(ordered) - 1)
    picked = sorted(set(picked))
    if len(picked) > max_points:
        picked = picked[: max_points - 1] + [len(ordered) - 1]
    return [ordered[i] for i in picked]


def downsample_series_points(
    points: list[SeriesPoint],
    max_points: int,
) -> list[SeriesPoint]:
    if len(points) <= max_points:
        return points

    segments = iter_series_segments(points)
    if len(segments) == 1 and not has_timeline_resets(ordered_pts_times(points)):
        ordered = sorted(points, key=lambda p: p.packet_index)
        return _downsample_ordered_series(ordered, max_points)

    sizes = [len(seg) for seg in segments]
    budgets = _segment_budgets(sizes, max_points)
    result: list[SeriesPoint] = []
    for seg, budget in zip(segments, budgets):
        ordered = sorted(seg, key=lambda p: p.packet_index)
        result.extend(_downsample_ordered_series(ordered, max(1, budget)))
    return sorted(result, key=lambda p: p.packet_index)


def downsample_pcr_points(
    points: list[PcrPoint],
    max_points: int,
) -> list[PcrPoint]:
    if len(points) <= max_points:
        return points

    segments = iter_pcr_segments(points)
    pcr_times = [p.pcr_time for p in sorted(points, key=lambda p: p.packet_index)]
    if len(segments) == 1 and not has_timeline_resets(pcr_times):
        ordered = sorted(points, key=lambda p: p.packet_index)
        return _downsample_ordered_pcr(ordered, max_points)

    sizes = [len(seg) for seg in segments]
    budgets = _segment_budgets(sizes, max_points)
    result: list[PcrPoint] = []
    for seg, budget in zip(segments, budgets):
        ordered = sorted(seg, key=lambda p: p.packet_index)
        result.extend(_downsample_ordered_pcr(ordered, max(1, budget)))
    return sorted(result, key=lambda p: p.packet_index)
