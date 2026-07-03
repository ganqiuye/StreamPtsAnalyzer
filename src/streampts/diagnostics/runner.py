from __future__ import annotations

from streampts.config import AppConfig
from streampts.diagnostics.av_sync import compute_av_sync
from streampts.diagnostics.jump import detect_jumps
from streampts.diagnostics.pcr import compute_pcr_intervals
from streampts.models import DiagnosticsResult, ProgramSeries, StreamInfo


def run_diagnostics(
    series: ProgramSeries,
    streams: list[StreamInfo],
    config: AppConfig,
) -> DiagnosticsResult:
    stream_diagnostics = {}

    for idx, pts in series.video_streams.items():
        stream_diagnostics[idx] = detect_jumps(idx, pts, config.jump)
    for idx, pts in series.audio_streams.items():
        if idx not in stream_diagnostics:
            stream_diagnostics[idx] = detect_jumps(idx, pts, config.jump)

    video_idx = series.default_video
    audio_idx = series.default_audio
    video_pts = series.video_streams.get(video_idx, []) if video_idx is not None else []
    audio_pts = series.audio_streams.get(audio_idx, []) if audio_idx is not None else []

    av_points, av_stats = compute_av_sync(video_pts, audio_pts, config.av_sync)
    pcr_intervals, pcr_stats = compute_pcr_intervals(series.pcr_points, config.pcr)

    return DiagnosticsResult(
        stream_diagnostics=stream_diagnostics,
        av_sync=av_points,
        av_stats=av_stats,
        pcr_intervals=pcr_intervals,
        pcr_stats=pcr_stats,
        video_stream_index=video_idx,
        audio_stream_index=audio_idx,
    )
