from __future__ import annotations

from streampts.config import PcrConfig
from streampts.models import PcrIntervalPoint, PcrPoint, PcrStats
from streampts.utils.timeline import continuous_time_lookup_pcr, iter_pcr_segments

IDEAL_PCR_INTERVAL_MS = 40.0


def compute_pcr_intervals(
    pcr_points: list[PcrPoint], config: PcrConfig
) -> tuple[list[PcrIntervalPoint], PcrStats | None]:
    if len(pcr_points) < 2:
        count = len(pcr_points)
        if count == 0:
            return [], None
        return [], PcrStats(
            point_count=count,
            mean_interval_ms=0.0,
            max_jitter_ms=0.0,
            anomaly_count=0,
        )

    timeline_lookup = continuous_time_lookup_pcr(pcr_points)
    intervals: list[PcrIntervalPoint] = []
    anomaly_count = 0
    jitter_vals: list[float] = []
    interval_vals: list[float] = []
    total_points = 0

    for seg in iter_pcr_segments(pcr_points):
        ordered = sorted(seg, key=lambda p: p.packet_index)
        total_points += len(ordered)
        for i in range(1, len(ordered)):
            dt = (ordered[i].pcr_time - ordered[i - 1].pcr_time) * 1000.0
            if dt < 0:
                continue
            jitter = dt - IDEAL_PCR_INTERVAL_MS
            is_anomaly = dt < config.interval_min_ms or dt > config.interval_max_ms
            if is_anomaly:
                anomaly_count += 1
            curr = ordered[i]
            intervals.append(
                PcrIntervalPoint(
                    time=curr.pcr_time,
                    timeline_time=timeline_lookup.get(curr.packet_index, curr.pcr_time),
                    interval_ms=dt,
                    jitter_ms=jitter,
                    is_anomaly=is_anomaly,
                )
            )
            jitter_vals.append(abs(jitter))
            interval_vals.append(dt)

    return intervals, PcrStats(
        point_count=total_points,
        mean_interval_ms=sum(interval_vals) / len(interval_vals) if interval_vals else 0.0,
        max_jitter_ms=max(jitter_vals) if jitter_vals else 0.0,
        anomaly_count=anomaly_count,
    )
