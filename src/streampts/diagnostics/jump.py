from __future__ import annotations

import statistics

from streampts.config import JumpConfig
from streampts.models import (
    DiscontinuityEvent,
    JumpSeverity,
    JumpType,
    SeriesPoint,
    StreamDiagnostics,
)
from streampts.utils.timeline import iter_series_segments
from streampts.utils.units import ms_from_pts_delta


def _median_positive(deltas: list[int]) -> float:
    pos = [d for d in deltas if d > 0]
    if not pos:
        return 3600.0  # 40ms @ 90k
    return float(statistics.median(pos))


def _segment_boundary_event(
    stream_index: int,
    prev_pt: SeriesPoint,
    curr: SeriesPoint,
) -> DiscontinuityEvent:
    delta = curr.pts - prev_pt.pts
    return DiscontinuityEvent(
        stream_index=stream_index,
        packet_index=curr.packet_index,
        pts=curr.pts,
        pts_time=curr.pts_time,
        jump_type=JumpType.DISCONTINUITY,
        severity=JumpSeverity.SEVERE,
        delta_pts=delta,
        delta_ms=ms_from_pts_delta(delta),
        flags=curr.flags,
        prev_pts=prev_pt.pts,
        prev_pts_time=prev_pt.pts_time,
        prev_packet_index=prev_pt.packet_index,
    )


def _detect_jumps_in_segment(
    stream_index: int,
    points: list[SeriesPoint],
    config: JumpConfig,
) -> list[DiscontinuityEvent]:
    if len(points) < 2:
        return []

    sorted_pts = sorted(points, key=lambda p: (p.pts_time, p.packet_index))
    deltas = [
        sorted_pts[i].pts - sorted_pts[i - 1].pts for i in range(1, len(sorted_pts))
    ]
    median = _median_positive(deltas)
    relative_threshold = median * config.factor
    min_pts = config.min_ms * 90.0
    max_pts = config.max_ms * 90.0 if config.max_ms is not None else None

    events: list[DiscontinuityEvent] = []
    for i in range(1, len(sorted_pts)):
        prev_pt = sorted_pts[i - 1]
        curr = sorted_pts[i]
        delta = curr.pts - prev_pt.pts
        delta_ms = ms_from_pts_delta(delta)
        has_disc_flag = "D" in curr.flags.upper() or "D" in prev_pt.flags.upper()

        if has_disc_flag:
            events.append(
                DiscontinuityEvent(
                    stream_index=stream_index,
                    packet_index=curr.packet_index,
                    pts=curr.pts,
                    pts_time=curr.pts_time,
                    jump_type=JumpType.DISCONTINUITY,
                    severity=JumpSeverity.SEVERE,
                    delta_pts=delta,
                    delta_ms=delta_ms,
                    flags=curr.flags,
                    prev_pts=prev_pt.pts,
                    prev_pts_time=prev_pt.pts_time,
                    prev_packet_index=prev_pt.packet_index,
                )
            )
            continue

        if delta < 0:
            events.append(
                DiscontinuityEvent(
                    stream_index=stream_index,
                    packet_index=curr.packet_index,
                    pts=curr.pts,
                    pts_time=curr.pts_time,
                    jump_type=JumpType.BACKWARD,
                    severity=JumpSeverity.SEVERE,
                    delta_pts=delta,
                    delta_ms=delta_ms,
                    flags=curr.flags,
                    prev_pts=prev_pt.pts,
                    prev_pts_time=prev_pt.pts_time,
                    prev_packet_index=prev_pt.packet_index,
                )
            )
            continue

        if delta <= min_pts:
            continue

        is_jump = delta > relative_threshold
        if not is_jump:
            continue

        if max_pts is not None and delta > max_pts:
            severity = JumpSeverity.SEVERE
        elif delta > relative_threshold:
            severity = JumpSeverity.OBVIOUS
        else:
            severity = JumpSeverity.MINOR

        events.append(
            DiscontinuityEvent(
                stream_index=stream_index,
                packet_index=curr.packet_index,
                pts=curr.pts,
                pts_time=curr.pts_time,
                jump_type=JumpType.JUMP,
                severity=severity,
                delta_pts=delta,
                delta_ms=delta_ms,
                flags=curr.flags,
                prev_pts=prev_pt.pts,
                prev_pts_time=prev_pt.pts_time,
                prev_packet_index=prev_pt.packet_index,
            )
        )

    return events


def detect_jumps(
    stream_index: int,
    points: list[SeriesPoint],
    config: JumpConfig,
) -> StreamDiagnostics:
    if not points:
        return StreamDiagnostics(stream_index=stream_index, packet_count=0)

    segments = iter_series_segments(points)
    events: list[DiscontinuityEvent] = []

    if len(segments) > 1:
        for i in range(1, len(segments)):
            prev_seg = sorted(segments[i - 1], key=lambda p: p.packet_index)
            curr_seg = sorted(segments[i], key=lambda p: p.packet_index)
            prev_pt = max(prev_seg, key=lambda p: (p.pts_time, p.packet_index))
            curr_pt = min(curr_seg, key=lambda p: (p.pts_time, p.packet_index))
            events.append(
                _segment_boundary_event(stream_index, prev_pt, curr_pt)
            )
    else:
        for seg in segments:
            events.extend(_detect_jumps_in_segment(stream_index, seg, config))

    events.sort(key=lambda e: e.packet_index)
    return StreamDiagnostics(
        stream_index=stream_index,
        packet_count=len(points),
        jumps=events,
    )


def top_annotated_jumps(
    diagnostics: StreamDiagnostics, annotate_top: int
) -> set[int]:
    """Return packet indices that receive text labels on chart."""
    ranked = sorted(
        diagnostics.jumps,
        key=lambda e: abs(e.delta_pts),
        reverse=True,
    )
    return {e.packet_index for e in ranked[:annotate_top]}
