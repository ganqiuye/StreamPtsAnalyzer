from __future__ import annotations

from streampts.models import PcrPoint, SeriesPoint

# pts_time 回退超过该阈值（秒）视为新段开始
TIMELINE_RESET_THRESHOLD_S = 1.0
# 分段衔接处留出极小间隔，便于跳变标记与虚线可见
SEGMENT_GAP_S = 0.04


def has_timeline_resets(times: list[float], threshold: float = TIMELINE_RESET_THRESHOLD_S) -> bool:
    if len(times) < 2:
        return False
    prev = times[0]
    for t in times[1:]:
        if t < prev - threshold:
            return True
        prev = t
    return False


def continuous_times(
    times: list[float],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> list[float]:
    """将分段重复的 pts_time 展开为单调递增的时间轴（用于图表 X 轴）。"""
    if not times:
        return []
    offset = 0.0
    seg_base = times[0]
    prev_t = times[0]
    anchor = times[0]
    result: list[float] = []
    for t in times:
        if t < prev_t - threshold:
            offset += prev_t - seg_base + SEGMENT_GAP_S
            seg_base = t
        result.append(anchor + offset + (t - seg_base))
        prev_t = t
    return result


def _ordered_by_packet(points: list[SeriesPoint]) -> list[SeriesPoint]:
    return sorted(points, key=lambda p: p.packet_index)


def continuous_times_for_points(
    points: list[SeriesPoint],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> list[float]:
    ordered = _ordered_by_packet(points)
    raw = [p.pts_time for p in ordered]
    cont = continuous_times(raw, threshold=threshold)
    by_packet = {p.packet_index: t for p, t in zip(ordered, cont)}
    return [by_packet[p.packet_index] for p in points]


def continuous_times_for_pcr(
    points: list[PcrPoint],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> list[float]:
    ordered = sorted(points, key=lambda p: p.packet_index)
    raw = [p.pcr_time for p in ordered]
    cont = continuous_times(raw, threshold=threshold)
    by_packet = {p.packet_index: t for p, t in zip(ordered, cont)}
    return [by_packet[p.packet_index] for p in points]


def iter_series_segments(
    points: list[SeriesPoint],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> list[list[SeriesPoint]]:
    ordered = _ordered_by_packet(points)
    if not ordered:
        return []
    segments: list[list[SeriesPoint]] = []
    current: list[SeriesPoint] = []
    prev_t = ordered[0].pts_time
    for p in ordered:
        if current and p.pts_time < prev_t - threshold:
            segments.append(current)
            current = []
        current.append(p)
        prev_t = p.pts_time
    if current:
        segments.append(current)
    return segments


def iter_pcr_segments(
    points: list[PcrPoint],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> list[list[PcrPoint]]:
    ordered = sorted(points, key=lambda p: p.packet_index)
    if not ordered:
        return []
    segments: list[list[PcrPoint]] = []
    current: list[PcrPoint] = []
    prev_t = ordered[0].pcr_time
    for p in ordered:
        if current and p.pcr_time < prev_t - threshold:
            segments.append(current)
            current = []
        current.append(p)
        prev_t = p.pcr_time
    if current:
        segments.append(current)
    return segments


def continuous_time_lookup(
    points: list[SeriesPoint],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> dict[int, float]:
    ordered = _ordered_by_packet(points)
    raw = [p.pts_time for p in ordered]
    cont = continuous_times(raw, threshold=threshold)
    return {p.packet_index: t for p, t in zip(ordered, cont)}


def continuous_time_lookup_pcr(
    points: list[PcrPoint],
    *,
    threshold: float = TIMELINE_RESET_THRESHOLD_S,
) -> dict[int, float]:
    ordered = sorted(points, key=lambda p: p.packet_index)
    raw = [p.pcr_time for p in ordered]
    cont = continuous_times(raw, threshold=threshold)
    return {p.packet_index: t for p, t in zip(ordered, cont)}


def ordered_pts_times(points: list[SeriesPoint]) -> list[float]:
    return [p.pts_time for p in _ordered_by_packet(points)]
