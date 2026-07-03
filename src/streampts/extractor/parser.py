from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np

from streampts.config import AppConfig
from streampts.extractor.ffprobe import run_ffprobe
from streampts.models import (
    AnalysisResult,
    PacketPoint,
    PcrPoint,
    ProgramInfo,
    ProgramSeries,
    SeriesPoint,
    StreamInfo,
)
from streampts.utils.downsample import lttb_downsample


def _int_or_none(value: object) -> int | None:
    if value is None or value == "N/A":
        return None
    return int(value)


def _float_or_none(value: object) -> float | None:
    if value is None or value == "N/A":
        return None
    return float(value)


def _parse_streams(raw: dict) -> list[StreamInfo]:
    streams: list[StreamInfo] = []
    for s in raw.get("streams", []):
        streams.append(
            StreamInfo(
                index=int(s["index"]),
                codec_type=s.get("codec_type", "unknown"),
                codec_name=s.get("codec_name", "unknown"),
                time_base=s.get("time_base", "1/90000"),
            )
        )
    return streams


def _parse_programs(raw: dict) -> list[ProgramInfo]:
    programs: list[ProgramInfo] = []
    for p in raw.get("programs", []):
        indices = []
        for s in p.get("streams", []):
            if isinstance(s, int):
                indices.append(int(s))
            elif "stream_index" in s:
                indices.append(int(s["stream_index"]))
            elif "index" in s:
                indices.append(int(s["index"]))
        programs.append(ProgramInfo(program_id=int(p["program_id"]), stream_indices=indices))
    return programs


def _assign_program_ids(streams: list[StreamInfo], programs: list[ProgramInfo]) -> None:
    index_map = {s.index: s for s in streams}
    for prog in programs:
        for idx in prog.stream_indices:
            if idx in index_map:
                index_map[idx].program_ids.append(prog.program_id)


def _parse_packets(raw: dict) -> list[PacketPoint]:
    packets: list[PacketPoint] = []
    for i, pkt in enumerate(raw.get("packets", [])):
        pts = _int_or_none(pkt.get("pts"))
        pts_time = _float_or_none(pkt.get("pts_time"))
        dts = _int_or_none(pkt.get("dts"))
        dts_time = _float_or_none(pkt.get("dts_time"))
        if pts is None:
            pts = _int_or_none(pkt.get("best_effort_timestamp"))
        if pts_time is None:
            pts_time = _float_or_none(pkt.get("best_effort_timestamp_time"))
        packets.append(
            PacketPoint(
                packet_index=i,
                stream_index=_int_or_none(pkt.get("stream_index")),
                pts=pts,
                pts_time=pts_time,
                dts=dts,
                dts_time=dts_time,
                pcr=_int_or_none(pkt.get("pcr")),
                pcr_time=_float_or_none(pkt.get("pcr_time")),
                flags=str(pkt.get("flags", "")),
            )
        )
    return packets


def _to_series_point(pkt: PacketPoint) -> SeriesPoint | None:
    if pkt.stream_index is None:
        return None
    pts = pkt.pts if pkt.pts is not None else pkt.dts
    pts_time = pkt.pts_time if pkt.pts_time is not None else pkt.dts_time
    if pts is None or pts_time is None:
        return None
    return SeriesPoint(
        packet_index=pkt.packet_index,
        stream_index=pkt.stream_index,
        pts=pts,
        pts_time=pts_time,
        dts=pkt.dts,
        flags=pkt.flags,
    )


def _downsample_series(points: list[SeriesPoint], max_points: int) -> list[SeriesPoint]:
    if len(points) <= max_points:
        return points
    x = np.array([p.pts_time for p in points])
    y = np.array([float(p.pts) for p in points])
    sx, sy = lttb_downsample(x, y, max_points)
    idxs = set(int(np.argmin(np.abs(x - vx))) for vx in sx)
    return [points[i] for i in sorted(idxs)]


def _downsample_pcr(points: list[PcrPoint], max_points: int) -> list[PcrPoint]:
    if len(points) <= max_points:
        return points
    x = np.array([p.pcr_time for p in points])
    y = np.array([float(p.pcr or 0) for p in points])
    sx, _ = lttb_downsample(x, y, max_points)
    idxs = set(int(np.argmin(np.abs(x - vx))) for vx in sx)
    return [points[i] for i in sorted(idxs)]


def _build_program_series(
    streams: list[StreamInfo],
    programs: list[ProgramInfo],
    packets: list[PacketPoint],
    max_points: int,
    downsample: bool,
) -> tuple[list[ProgramSeries], bool, dict[str, int]]:
    stream_type = {s.index: s.codec_type for s in streams}
    pcr_all: list[PcrPoint] = []
    for pkt in packets:
        if pkt.pcr_time is not None:
            pcr_all.append(
                PcrPoint(packet_index=pkt.packet_index, pcr=pkt.pcr, pcr_time=pkt.pcr_time)
            )

    original_counts = {
        "pcr": len(pcr_all),
        "video": 0,
        "audio": 0,
    }

    program_list = programs or [ProgramInfo(program_id=-1, stream_indices=[s.index for s in streams])]
    result: list[ProgramSeries] = []
    any_downsampled = False

    for prog in program_list:
        video: dict[int, list[SeriesPoint]] = {}
        audio: dict[int, list[SeriesPoint]] = {}

        for pkt in packets:
            sp = _to_series_point(pkt)
            if sp is None or sp.stream_index not in prog.stream_indices:
                continue
            ctype = stream_type.get(sp.stream_index, "")
            if ctype == "video":
                video.setdefault(sp.stream_index, []).append(sp)
                original_counts["video"] += 1
            elif ctype == "audio":
                audio.setdefault(sp.stream_index, []).append(sp)
                original_counts["audio"] += 1

        if downsample:
            for idx in list(video.keys()):
                before = len(video[idx])
                video[idx] = _downsample_series(video[idx], max_points)
                any_downsampled = any_downsampled or len(video[idx]) < before
            for idx in list(audio.keys()):
                before = len(audio[idx])
                audio[idx] = _downsample_series(audio[idx], max_points)
                any_downsampled = any_downsampled or len(audio[idx]) < before

        pcr = pcr_all
        if downsample and len(pcr) > max_points:
            before = len(pcr)
            pcr = _downsample_pcr(pcr, max_points)
            any_downsampled = any_downsampled or len(pcr) < before

        default_video = next(iter(sorted(video)), None)
        default_audio = next(iter(sorted(audio)), None)

        result.append(
            ProgramSeries(
                program_id=prog.program_id if prog.program_id >= 0 else None,
                video_streams=video,
                audio_streams=audio,
                pcr_points=pcr,
                default_video=default_video,
                default_audio=default_audio,
            )
        )

    return result, any_downsampled, original_counts


def extract_analysis(
    input_path: Path,
    ffprobe_bin: str,
    config: AppConfig,
    *,
    time_range: str | None = None,
    force_full: bool = False,
    verbose: bool = False,
    progress: Optional[Callable[[str], None]] = None,
) -> AnalysisResult:
    def notify(message: str) -> None:
        if progress is not None:
            progress(message)

    notify("正在读取流信息…")
    meta = run_ffprobe(ffprobe_bin, input_path, timeout=config.timeout, verbose=verbose)
    streams = _parse_streams(meta)
    programs = _parse_programs(meta)
    _assign_program_ids(streams, programs)

    fmt = meta.get("format", {})
    format_name = fmt.get("format_name", "unknown")
    duration = _float_or_none(fmt.get("duration"))

    file_mb = input_path.stat().st_size / (1024 * 1024)
    downsample = not force_full and file_mb >= config.threshold_mb

    read_interval = None
    if time_range:
        from streampts.extractor.ffprobe import parse_time_range

        read_interval = parse_time_range(time_range)

    notify(f"正在提取包数据（{file_mb:.0f} MB，可能需要 1–3 分钟）…")
    pkt_raw = run_ffprobe(
        ffprobe_bin,
        input_path,
        show_packets=True,
        read_interval=read_interval,
        timeout=config.timeout,
        verbose=verbose,
    )
    notify("正在解析包数据…")
    packets = _parse_packets(pkt_raw)

    notify("正在整理节目数据…")
    program_series, any_downsampled, original_counts = _build_program_series(
        streams, programs, packets, config.max_points, downsample
    )

    return AnalysisResult(
        input_path=str(input_path),
        format_name=format_name,
        duration=duration,
        streams=streams,
        programs=programs,
        program_series=program_series,
        downsampled=any_downsampled,
        original_counts=original_counts,
    )
