from __future__ import annotations

from streampts.config import PcrConfig
from streampts.models import PcrIntervalPoint, PcrPoint, PcrStats

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

    sorted_pcr = sorted(pcr_points, key=lambda p: p.pcr_time)
    intervals: list[PcrIntervalPoint] = []
    anomaly_count = 0
    jitter_vals: list[float] = []
    interval_vals: list[float] = []

    for i in range(1, len(sorted_pcr)):
        dt = (sorted_pcr[i].pcr_time - sorted_pcr[i - 1].pcr_time) * 1000.0
        jitter = dt - IDEAL_PCR_INTERVAL_MS
        is_anomaly = dt < config.interval_min_ms or dt > config.interval_max_ms
        if is_anomaly:
            anomaly_count += 1
        intervals.append(
            PcrIntervalPoint(
                time=sorted_pcr[i].pcr_time,
                interval_ms=dt,
                jitter_ms=jitter,
                is_anomaly=is_anomaly,
            )
        )
        jitter_vals.append(abs(jitter))
        interval_vals.append(dt)

    return intervals, PcrStats(
        point_count=len(sorted_pcr),
        mean_interval_ms=sum(interval_vals) / len(interval_vals),
        max_jitter_ms=max(jitter_vals) if jitter_vals else 0.0,
        anomaly_count=anomaly_count,
    )
