from __future__ import annotations

import bisect
import statistics

from streampts.config import AvSyncConfig
from streampts.models import AvSyncPoint, AvSyncStats, SeriesPoint


def _nearest_audio(
    video_time: float, audio_times: list[float], audio_pts: list[int]
) -> tuple[int, float]:
    if not audio_times:
        return 0, 0.0
    idx = bisect.bisect_left(audio_times, video_time)
    if idx == 0:
        return audio_pts[0], ms_delta(audio_pts[0], video_time, audio_times[0])
    if idx >= len(audio_times):
        return audio_pts[-1], ms_delta(audio_pts[-1], video_time, audio_times[-1])

    t0, t1 = audio_times[idx - 1], audio_times[idx]
    if abs(video_time - t0) <= abs(t1 - video_time):
        return audio_pts[idx - 1], ms_delta_from_times(t0, video_time, audio_pts[idx - 1])
    return audio_pts[idx], ms_delta_from_times(t1, video_time, audio_pts[idx])


def ms_delta(audio_pts: int, video_time: float, audio_time: float) -> float:
    video_pts_equiv = int(video_time * 90000)
    return (audio_pts - video_pts_equiv) / 90.0


def ms_delta_from_times(audio_time: float, video_time: float, audio_pts: int) -> float:
    video_pts_equiv = int(video_time * 90000)
    return (audio_pts - video_pts_equiv) / 90.0


def compute_av_sync(
    video: list[SeriesPoint],
    audio: list[SeriesPoint],
    config: AvSyncConfig,
) -> tuple[list[AvSyncPoint], AvSyncStats | None]:
    if not video or not audio:
        return [], None

    audio_sorted = sorted(audio, key=lambda p: p.pts_time)
    audio_times = [p.pts_time for p in audio_sorted]
    audio_pts = [p.pts for p in audio_sorted]

    points: list[AvSyncPoint] = []
    for vp in sorted(video, key=lambda p: p.pts_time):
        a_pts, _ = _nearest_audio(vp.pts_time, audio_times, audio_pts)
        delta_ms = (a_pts - vp.pts) / 90.0
        points.append(
            AvSyncPoint(
                time=vp.pts_time,
                video_pts=vp.pts,
                audio_pts=a_pts,
                delta_ms=delta_ms,
            )
        )

    deltas = [p.delta_ms for p in points]
    stats = AvSyncStats(
        mean_ms=float(statistics.mean(deltas)),
        max_ms=max(deltas),
        min_ms=min(deltas),
        std_ms=float(statistics.pstdev(deltas)) if len(deltas) > 1 else 0.0,
        exceed_count=sum(1 for d in deltas if abs(d) > config.threshold_ms),
    )
    return points, stats
