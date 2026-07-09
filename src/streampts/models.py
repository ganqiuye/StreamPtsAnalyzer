from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class JumpType(str, Enum):
    BACKWARD = "backward"
    JUMP = "jump"
    DISCONTINUITY = "discontinuity"


class JumpSeverity(str, Enum):
    MINOR = "minor"
    OBVIOUS = "obvious"
    SEVERE = "severe"


@dataclass
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str
    time_base: str
    program_ids: list[int] = field(default_factory=list)


@dataclass
class ProgramInfo:
    program_id: int
    stream_indices: list[int] = field(default_factory=list)
    pcr_pid: int | None = None

    @property
    def default_video_index(self) -> int | None:
        return next((i for i in self.stream_indices if True), None)


@dataclass
class PacketPoint:
    packet_index: int
    stream_index: int | None
    pts: int | None
    pts_time: float | None
    dts: int | None = None
    dts_time: float | None = None
    pcr: int | None = None
    pcr_time: float | None = None
    flags: str = ""


@dataclass
class SeriesPoint:
    packet_index: int
    stream_index: int | None
    pts: int
    pts_time: float
    dts: int | None = None
    flags: str = ""


@dataclass
class PcrPoint:
    packet_index: int
    pcr: int | None
    pcr_time: float

    @property
    def base_90k(self) -> int:
        if self.pcr is not None:
            return self.pcr // 300
        return int(round(self.pcr_time * 90_000))

    @property
    def full_27m(self) -> int:
        if self.pcr is not None:
            return self.pcr
        return int(round(self.pcr_time * 27_000_000))

    @property
    def ext(self) -> int:
        if self.pcr is not None:
            return self.pcr - self.base_90k * 300
        return self.full_27m - self.base_90k * 300


@dataclass
class DiscontinuityEvent:
    stream_index: int
    packet_index: int
    pts: int
    pts_time: float
    jump_type: JumpType
    severity: JumpSeverity
    delta_pts: int
    delta_ms: float
    flags: str = ""
    prev_pts: int = 0
    prev_pts_time: float = 0.0
    prev_packet_index: int = -1


@dataclass
class AvSyncPoint:
    time: float
    video_pts: int
    audio_pts: int
    delta_ms: float
    timeline_time: float = 0.0


@dataclass
class AvSyncStats:
    mean_ms: float
    max_ms: float
    min_ms: float
    std_ms: float
    exceed_count: int


@dataclass
class PcrIntervalPoint:
    time: float
    interval_ms: float
    jitter_ms: float
    is_anomaly: bool
    timeline_time: float = 0.0


@dataclass
class PcrStats:
    point_count: int
    mean_interval_ms: float
    max_jitter_ms: float
    anomaly_count: int


@dataclass
class StreamDiagnostics:
    stream_index: int
    packet_count: int
    jumps: list[DiscontinuityEvent] = field(default_factory=list)

    @property
    def backward_count(self) -> int:
        return sum(1 for j in self.jumps if j.jump_type == JumpType.BACKWARD)

    @property
    def jump_count(self) -> int:
        return sum(
            1
            for j in self.jumps
            if j.jump_type in (JumpType.JUMP, JumpType.DISCONTINUITY)
        )


@dataclass
class ProgramSeries:
    program_id: int | None
    video_streams: dict[int, list[SeriesPoint]]
    audio_streams: dict[int, list[SeriesPoint]]
    pcr_points: list[PcrPoint]
    default_video: int | None
    default_audio: int | None


@dataclass
class AnalysisResult:
    input_path: str
    format_name: str
    duration: float | None
    streams: list[StreamInfo]
    programs: list[ProgramInfo]
    program_series: list[ProgramSeries]
    downsampled: bool = False
    original_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class DiagnosticsResult:
    stream_diagnostics: dict[int, StreamDiagnostics]
    av_sync: list[AvSyncPoint]
    av_stats: AvSyncStats | None
    pcr_intervals: list[PcrIntervalPoint]
    pcr_stats: PcrStats | None
    video_stream_index: int | None
    audio_stream_index: int | None


UnitName = Literal["90k", "us", "ms", "sec"]
