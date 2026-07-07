from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from streampts.config import AppConfig
from streampts.diagnostics.runner import run_diagnostics
from streampts.models import (
    AnalysisResult,
    DiagnosticsResult,
    DiscontinuityEvent,
    PcrPoint,
    ProgramSeries,
    SeriesPoint,
    StreamInfo,
    UnitName,
)
from streampts.utils.units import (
    format_time,
    pts_us_from_time,
    unit_label,
)

from streampts.utils.downsample import lttb_downsample
from streampts.utils.timeline import (
    SEGMENT_GAP_S,
    TIMELINE_RESET_THRESHOLD_S,
    continuous_time_lookup,
    continuous_times_for_pcr,
    continuous_times_for_points,
    has_timeline_resets,
    ordered_pts_times,
)

PTS_Y_TICKFORMAT = ",d"
US_TO_90K = 90000.0 / 1_000_000.0
K90_TO_US = 1_000_000.0 / 90000.0
DISPLAY_MAX_POINTS = 2500
PTS_HOVER_TEMPLATE = (
    "%{customdata[0]}<br>"
    "Time: %{customdata[1]}<br>"
    "PTS: %{customdata[2]} (90k) | %{customdata[3]} (µs)<br>"
    "DTS: %{customdata[4]}<br>"
    "Packet #%{customdata[5]}<br>"
    "Flags: %{customdata[6]}"
    "<extra></extra>"
)

PTS_HOVER_SEGMENTED_TEMPLATE = (
    "%{customdata[0]}<br>"
    "Timeline: %{customdata[1]}<br>"
    "PTS Time: %{customdata[7]}<br>"
    "PTS: %{customdata[2]} (90k) | %{customdata[3]} (µs)<br>"
    "DTS: %{customdata[4]}<br>"
    "Packet #%{customdata[5]}<br>"
    "Flags: %{customdata[6]}"
    "<extra></extra>"
)

LayoutMode = Literal["combined", "separate"]


@dataclass(frozen=True)
class _SeparateRowPlan:
    kind: str
    stream_index: int | None
    row: int
    title: str


def _separate_row_plan(
    ps: ProgramSeries,
    streams: list[StreamInfo],
    has_pcr_data: bool,
    has_pcr_interval: bool,
    diag: DiagnosticsResult,
) -> list[_SeparateRowPlan]:
    plan: list[_SeparateRowPlan] = []
    row = 1
    for vidx in sorted(ps.video_streams.keys()):
        plan.append(
            _SeparateRowPlan(
                "video", vidx, row, f"{_stream_label(streams, vidx)} PTS"
            )
        )
        row += 1
    for aidx in sorted(ps.audio_streams.keys()):
        plan.append(
            _SeparateRowPlan(
                "audio", aidx, row, f"{_stream_label(streams, aidx)} PTS"
            )
        )
        row += 1
    if has_pcr_data and ps.pcr_points:
        plan.append(_SeparateRowPlan("pcr", None, row, "PCR"))
        row += 1
    if diag.av_sync:
        plan.append(_SeparateRowPlan("av", None, row, "A-V Delta (ms)"))
        row += 1
    if has_pcr_interval and diag.pcr_intervals:
        plan.append(_SeparateRowPlan("pcr_interval", None, row, "PCR Interval (ms)"))
    return plan


def _separate_row_for(
    plan: list[_SeparateRowPlan], kind: str, stream_index: int | None
) -> int:
    for item in plan:
        if item.kind == kind and item.stream_index == stream_index:
            return item.row
    return 1


def _meta_has_negative_pts(meta: list[dict]) -> bool:
    for m in meta:
        pairs = m.get("pts_pairs")
        if pairs:
            for pair in pairs:
                if pair[1] < 0:
                    return True
        for key in ("y_us", "y_90k"):
            ys = m.get(key)
            if not ys:
                continue
            for v in ys:
                if v is not None and v < 0:
                    return True
        jumps = m.get("jumps")
        if jumps:
            for j in jumps:
                if j[1] < 0 or j[3] < 0:
                    return True
    return False


def _pts_y_value(pts: int, pts_time: float, unit: UnitName) -> float:
    if unit == "us":
        return float(pts_us_from_time(pts_time))
    return float(pts)


def _display_points(
    points: list[SeriesPoint], max_pts: int
) -> tuple[list[SeriesPoint], list[float]]:
    timeline_x = continuous_times_for_points(points)
    if len(points) <= max_pts:
        return points, timeline_x
    import numpy as np

    x = np.array(timeline_x, dtype=float)
    y = np.array([float(p.pts) for p in points], dtype=float)
    sx, _ = lttb_downsample(x, y, max_pts)
    picked: list[int] = []
    seen: set[int] = set()
    for tx in sx:
        idx = int(np.argmin(np.abs(x - tx)))
        if idx not in seen:
            seen.add(idx)
            picked.append(idx)
    picked.sort()
    return [points[i] for i in picked], [timeline_x[i] for i in picked]


def _analysis_uses_timeline(analysis: AnalysisResult) -> bool:
    for ps in analysis.program_series:
        for pts in list(ps.video_streams.values()) + list(ps.audio_streams.values()):
            if has_timeline_resets(ordered_pts_times(pts)):
                return True
        if ps.pcr_points:
            pcr_times = [p.pcr_time for p in sorted(ps.pcr_points, key=lambda p: p.packet_index)]
            if has_timeline_resets(pcr_times):
                return True
    return False


def _program_uses_timeline(ps: ProgramSeries) -> bool:
    for pts in list(ps.video_streams.values()) + list(ps.audio_streams.values()):
        if has_timeline_resets(ordered_pts_times(pts)):
            return True
    if ps.pcr_points:
        pcr_times = [p.pcr_time for p in sorted(ps.pcr_points, key=lambda p: p.packet_index)]
        if has_timeline_resets(pcr_times):
            return True
    return False


def _xaxis_title(analysis: AnalysisResult) -> str:
    return "Timeline (s)" if _analysis_uses_timeline(analysis) else "Time (s)"


def _chart_x_values(points: list[SeriesPoint], timeline_x: list[float]) -> list[float]:
    if has_timeline_resets(ordered_pts_times(points)):
        return timeline_x
    return [p.pts_time for p in points]


def _pts_customdata(
    points: list[SeriesPoint],
    streams: list[StreamInfo],
    *,
    timeline_x: list[float] | None = None,
    segmented: bool = False,
) -> list[list]:
    rows: list[list] = []
    for i, p in enumerate(points):
        raw_time = format_time(p.pts_time)
        timeline = format_time(timeline_x[i]) if timeline_x else raw_time
        rows.append(
            [
                _stream_label(streams, p.stream_index or -1),
                timeline,
                str(p.pts),
                str(pts_us_from_time(p.pts_time)),
                str(p.dts if p.dts is not None else "N/A"),
                str(p.packet_index),
                p.flags or "—",
                raw_time if segmented else "",
            ]
        )
    return rows


def _y_from_pairs(pairs: list[list], unit: UnitName) -> list[float]:
    if unit == "us":
        return [float(pts_us_from_time(t)) for t, _ in pairs]
    return [float(pts) for _, pts in pairs]


def _pts_yaxis_kwargs(has_negative_pts: bool) -> dict:
    kw: dict = {"tickformat": PTS_Y_TICKFORMAT, "exponentformat": "none"}
    if not has_negative_pts:
        kw["rangemode"] = "tozero"
    return kw

LINE_COLORS = {
    "video": "#2563eb",
    "audio": "#dc2626",
    "pcr": "#16a34a",
    "av": "#0891b2",
    "pcr_interval": "#ca8a04",
}

PLOT_CONFIG = {
    "scrollZoom": False,
    "displaylogo": False,
    "responsive": True,
    "doubleClick": "reset",
    "modeBarButtonsToRemove": [
        "lasso2d",
        "select2d",
        "zoom2d",
        "zoomIn2d",
        "zoomOut2d",
        "autoScale2d",
    ],
}


def _plotly_cdn_tag() -> str:
    from plotly.offline.offline import get_plotlyjs_version

    version = get_plotlyjs_version()
    return (
        f'<script charset="utf-8" '
        f'src="https://cdn.plot.ly/plotly-{version}.min.js"></script>'
    )


def _stream_label(streams: list[StreamInfo], index: int) -> str:
    for s in streams:
        if s.index == index:
            return f"{s.codec_type} #{index} ({s.codec_name})"
    return f"stream #{index}"


class _FigureBuilder:
    def __init__(self, fig: go.Figure) -> None:
        self.fig = fig
        self.meta: list[dict] = []

    def _add(
        self,
        trace: go.Scatter,
        *,
        row: int,
        col: int = 1,
        secondary_y: bool = False,
        program: int,
        kind: str,
        extra_meta: dict | None = None,
    ) -> None:
        self.fig.add_trace(trace, row=row, col=col, secondary_y=secondary_y)
        entry: dict = {"program": program, "kind": kind, "row": row}
        if extra_meta:
            entry.update(extra_meta)
        self.meta.append(entry)

    def add_pts(
        self,
        name: str,
        x: list[float],
        pairs: list[list],
        row: int,
        program: int,
        kind: str,
        color: str,
        *,
        stream_index: int | None = None,
        customdata: list[list] | None = None,
        hover_template: str = PTS_HOVER_TEMPLATE,
        secondary_y: bool = False,
        default_unit: UnitName = "us",
    ) -> None:
        if not x:
            return
        y0 = _y_from_pairs(pairs, default_unit)
        self._add(
            go.Scattergl(
                name=name,
                x=x,
                y=y0,
                mode="markers",
                marker=dict(size=4, color=color, opacity=0.85),
                hovertemplate=hover_template,
                customdata=customdata,
            ),
            row=row,
            secondary_y=secondary_y,
            program=program,
            kind=kind,
            extra_meta={"pts_pairs": pairs, "stream_index": stream_index},
        )

    def add_interval_line(
        self,
        name: str,
        x: list[float],
        y: list[float],
        hover: list[str],
        row: int,
        program: int,
        kind: str,
        color: str,
    ) -> None:
        if not x:
            return
        self._add(
            go.Scattergl(
                name=name,
                x=x,
                y=y,
                mode="lines",
                line=dict(width=1.5, color=color),
                hovertext=hover,
                hoverinfo="text",
            ),
            row=row,
            program=program,
            kind=kind,
        )

    def add_jump_boundaries(
        self,
        events: list[DiscontinuityEvent],
        streams: list[StreamInfo],
        row: int,
        program: int,
        stream_kind: str,
        stream_index: int,
        default_unit: UnitName = "us",
        *,
        time_lookup: dict[int, float] | None = None,
    ) -> None:
        if not events:
            return

        def _x_time(packet_index: int, pts_time: float) -> float:
            if time_lookup and packet_index in time_lookup:
                return time_lookup[packet_index]
            return pts_time

        color = LINE_COLORS[stream_kind]
        label = f"{'Video' if stream_kind == 'video' else 'Audio'} 跳变"

        bx, by0, bhover, marker_text = [], [], [], []
        lx, ly0 = [], []
        jump_meta: list[list] = []
        for e in events:
            if e.prev_packet_index < 0:
                continue
            prev_x = _x_time(e.prev_packet_index, e.prev_pts_time)
            curr_x = _x_time(e.packet_index, e.pts_time)
            if curr_x <= prev_x:
                curr_x = prev_x + SEGMENT_GAP_S
            prev_y = _pts_y_value(e.prev_pts, e.prev_pts_time, default_unit)
            curr_y = _pts_y_value(e.pts, e.pts_time, default_unit)
            # jump_meta: [prev_pts_time, prev_pts, curr_pts_time, curr_pts] for JS unit switch
            jump_meta.append([e.prev_pts_time, e.prev_pts, e.pts_time, e.pts])
            bx.extend([prev_x, curr_x])
            by0.extend([prev_y, curr_y])
            marker_text.extend(
                [
                    str(int(prev_y)) if default_unit == "us" else str(e.prev_pts),
                    str(int(curr_y)) if default_unit == "us" else str(e.pts),
                ]
            )
            bhover.extend(
                [
                    (
                        f"跳变前<br>{_stream_label(streams, e.stream_index)}<br>"
                        f"Time: {format_time(e.prev_pts_time)}<br>"
                        f"PTS: {e.prev_pts} (90k) | {pts_us_from_time(e.prev_pts_time)} (µs)<br>"
                        f"Packet #{e.prev_packet_index}"
                    ),
                    (
                        f"跳变后<br>{_stream_label(streams, e.stream_index)}<br>"
                        f"Time: {format_time(e.pts_time)}<br>"
                        f"PTS: {e.pts} (90k) | {pts_us_from_time(e.pts_time)} (µs)<br>"
                        f"Packet #{e.packet_index}<br>"
                        f"Delta: {e.delta_pts:+d} ({e.delta_ms:+.3f} ms)<br>"
                        f"Type: {e.jump_type.value}"
                    ),
                ]
            )
            lx.extend([prev_x, curr_x, None])
            ly0.extend([prev_y, curr_y, None])

        self._add(
            go.Scattergl(
                name=f"{label} 连线",
                x=lx,
                y=ly0,
                mode="lines",
                line=dict(width=2, color="#f97316", dash="dash"),
                hoverinfo="skip",
                showlegend=True,
                connectgaps=False,
            ),
            row=row,
            program=program,
            kind=f"jump_link_{stream_kind}",
            extra_meta={
                "jumps": jump_meta,
                "jump_kind": "link",
                "stream_index": stream_index,
            },
        )
        self._add(
            go.Scatter(
                name=f"{label} PTS",
                x=bx,
                y=by0,
                mode="markers+text",
                text=marker_text,
                textposition="top center",
                textfont=dict(size=10, color="#0f172a"),
                marker=dict(
                    size=10,
                    color="#fef3c7",
                    symbol="square",
                    line=dict(width=1.5, color=color),
                ),
                hovertext=bhover,
                hoverinfo="text",
            ),
            row=row,
            program=program,
            kind=f"jump_{stream_kind}",
            extra_meta={
                "jumps": jump_meta,
                "jump_kind": "marker",
                "stream_index": stream_index,
            },
        )



def _add_program_traces(
    builder: _FigureBuilder,
    ps: ProgramSeries,
    diag: DiagnosticsResult,
    streams: list[StreamInfo],
    default_unit: UnitName,
    prog_idx: int,
    layout: LayoutMode,
    rows_map: dict[str, int],
    has_pcr_data: bool,
    *,
    separate_plan: list[_SeparateRowPlan] | None = None,
    has_pcr_interval: bool = False,
) -> None:
    prog_label = f"Program {ps.program_id}" if ps.program_id is not None else "All streams"
    program_segmented = False

    for vidx, vpts in ps.video_streams.items():
        if layout == "combined":
            row = rows_map["combined"]
        else:
            row = _separate_row_for(separate_plan or [], "video", vidx)
        display, timeline_x = _display_points(vpts, DISPLAY_MAX_POINTS)
        segmented = has_timeline_resets(ordered_pts_times(vpts))
        program_segmented = program_segmented or segmented
        chart_x = _chart_x_values(display, timeline_x)
        time_lookup = continuous_time_lookup(vpts) if segmented else None
        hover_tpl = PTS_HOVER_SEGMENTED_TEMPLATE if segmented else PTS_HOVER_TEMPLATE
        builder.add_pts(
            f"{prog_label} Video #{vidx}",
            chart_x,
            [[p.pts_time, p.pts] for p in display],
            row,
            prog_idx,
            "video",
            LINE_COLORS["video"],
            stream_index=vidx,
            customdata=_pts_customdata(
                display, streams, timeline_x=timeline_x, segmented=segmented
            ),
            hover_template=hover_tpl,
            default_unit=default_unit,
        )
        ev = diag.stream_diagnostics.get(vidx)
        if ev and ev.jumps:
            builder.add_jump_boundaries(
                ev.jumps,
                streams,
                row,
                prog_idx,
                "video",
                vidx,
                default_unit,
                time_lookup=time_lookup,
            )

    for aidx, apts in ps.audio_streams.items():
        if layout == "combined":
            row = rows_map["combined"]
        else:
            row = _separate_row_for(separate_plan or [], "audio", aidx)
        display, timeline_x = _display_points(apts, DISPLAY_MAX_POINTS)
        segmented = has_timeline_resets(ordered_pts_times(apts))
        program_segmented = program_segmented or segmented
        chart_x = _chart_x_values(display, timeline_x)
        time_lookup = continuous_time_lookup(apts) if segmented else None
        hover_tpl = PTS_HOVER_SEGMENTED_TEMPLATE if segmented else PTS_HOVER_TEMPLATE
        builder.add_pts(
            f"{prog_label} Audio #{aidx}",
            chart_x,
            [[p.pts_time, p.pts] for p in display],
            row,
            prog_idx,
            "audio",
            LINE_COLORS["audio"],
            stream_index=aidx,
            customdata=_pts_customdata(
                display, streams, timeline_x=timeline_x, segmented=segmented
            ),
            hover_template=hover_tpl,
            default_unit=default_unit,
        )
        ev = diag.stream_diagnostics.get(aidx)
        if ev and ev.jumps:
            builder.add_jump_boundaries(
                ev.jumps,
                streams,
                row,
                prog_idx,
                "audio",
                aidx,
                default_unit,
                time_lookup=time_lookup,
            )

    if has_pcr_data and ps.pcr_points:
        if layout == "combined":
            row = rows_map["combined"]
            secondary_y = True
        else:
            row = _separate_row_for(separate_plan or [], "pcr", None)
            secondary_y = False
        pcr_all = ps.pcr_points
        pcr_timeline = continuous_times_for_pcr(pcr_all)
        pcr_segmented = has_timeline_resets(
            [p.pcr_time for p in sorted(pcr_all, key=lambda p: p.packet_index)]
        )
        program_segmented = program_segmented or pcr_segmented
        if len(pcr_all) > DISPLAY_MAX_POINTS:
            step = len(pcr_all) / DISPLAY_MAX_POINTS
            indices = [int(i * step) for i in range(DISPLAY_MAX_POINTS)]
            pcr_display = [pcr_all[i] for i in indices]
            pcr_x = [pcr_timeline[i] for i in indices]
        else:
            pcr_display = pcr_all
            pcr_x = pcr_timeline
        if not pcr_segmented:
            pcr_x = [p.pcr_time for p in pcr_display]
        pairs = [
            [p.pcr_time, p.pcr or int(p.pcr_time * 90000)] for p in pcr_display
        ]
        builder.add_pts(
            f"{prog_label} PCR",
            pcr_x,
            pairs,
            row,
            prog_idx,
            "pcr",
            LINE_COLORS["pcr"],
            stream_index=None,
            customdata=[
                [
                    "PCR",
                    format_time(pcr_x[i]),
                    str(p.pcr),
                    str(pts_us_from_time(p.pcr_time)),
                    "N/A",
                    str(p.packet_index),
                    "—",
                    format_time(p.pcr_time) if pcr_segmented else "",
                ]
                for i, p in enumerate(pcr_display)
            ],
            hover_template=(
                PTS_HOVER_SEGMENTED_TEMPLATE if pcr_segmented else PTS_HOVER_TEMPLATE
            ),
            secondary_y=secondary_y,
            default_unit=default_unit,
        )

    if diag.av_sync:
        if layout == "combined":
            row = rows_map["av"]
        else:
            row = _separate_row_for(separate_plan or [], "av", None)
        av_x = [p.timeline_time for p in diag.av_sync]
        builder.add_interval_line(
            f"{prog_label} A-V Delta",
            av_x,
            [p.delta_ms for p in diag.av_sync],
            [
                (
                    f"A-V Delta: {p.delta_ms:.3f} ms<br>"
                    f"Timeline: {format_time(p.timeline_time)}<br>"
                    f"PTS Time: {format_time(p.time)}<br>"
                    f"Video PTS: {p.video_pts}<br>Audio PTS: {p.audio_pts}"
                    if program_segmented
                    else (
                        f"A-V Delta: {p.delta_ms:.3f} ms<br>"
                        f"Time: {format_time(p.time)}<br>"
                        f"Video PTS: {p.video_pts}<br>Audio PTS: {p.audio_pts}"
                    )
                )
                for p in diag.av_sync
            ],
            row,
            prog_idx,
            "av",
            LINE_COLORS["av"],
        )

    if has_pcr_interval and diag.pcr_intervals:
        if layout == "combined":
            row = rows_map["pcr_interval"]
        else:
            row = _separate_row_for(separate_plan or [], "pcr_interval", None)
        pcr_iv_x = [p.timeline_time for p in diag.pcr_intervals]
        builder.add_interval_line(
            f"{prog_label} PCR Interval",
            pcr_iv_x,
            [p.interval_ms for p in diag.pcr_intervals],
            [
                f"Interval: {p.interval_ms:.3f} ms<br>"
                f"Jitter: {p.jitter_ms:+.3f} ms<br>"
                f"Timeline: {format_time(p.timeline_time)}<br>"
                f"PTS Time: {format_time(p.time)}"
                if program_segmented
                else (
                    f"Interval: {p.interval_ms:.3f} ms<br>"
                    f"Jitter: {p.jitter_ms:+.3f} ms<br>"
                    f"Time: {format_time(p.time)}"
                )
                for p in diag.pcr_intervals
            ],
            row,
            prog_idx,
            "pcr_interval",
            LINE_COLORS["pcr_interval"],
        )


def build_figure(
    analysis: AnalysisResult,
    diagnostics_by_program: list[DiagnosticsResult],
    config: AppConfig,
    layout: LayoutMode,
    default_unit: UnitName = "us",
    default_program: int = 0,
) -> tuple[go.Figure, list[dict], bool]:
    if layout != "combined":
        raise ValueError("build_figure only supports combined layout")

    has_pcr_data = any(ps.pcr_points for ps in analysis.program_series)
    has_pcr_interval = any(d.pcr_intervals for d in diagnostics_by_program)

    pts_title = "PTS — Video / Audio / PCR" if has_pcr_data else "PTS — Video / Audio"
    if has_pcr_interval:
        titles = [pts_title, "A-V Delta (ms)", "PCR Interval (ms)"]
        heights = [0.55, 0.25, 0.20]
    else:
        titles = [pts_title, "A-V Delta (ms)"]
        heights = [0.62, 0.38]
    specs: list[dict] = [{"secondary_y": True}] if has_pcr_data else [{}]
    specs.extend({} for _ in range(len(titles) - 1))
    rows_map: dict[str, int] = {
        "combined": 1,
        "av": 2,
    }
    if has_pcr_interval:
        rows_map["pcr_interval"] = 3

    total = sum(heights)
    fig = make_subplots(
        rows=len(titles),
        cols=1,
        shared_xaxes=True,
        shared_yaxes=False,
        vertical_spacing=0.04,
        row_heights=[h / total for h in heights],
        subplot_titles=[f"<b>{t}</b>" for t in titles],
        specs=[[specs[i]] for i in range(len(titles))],
    )
    builder = _FigureBuilder(fig)

    for prog_idx, (ps, diag) in enumerate(
        zip(analysis.program_series, diagnostics_by_program)
    ):
        _add_program_traces(
            builder,
            ps,
            diag,
            analysis.streams,
            default_unit,
            prog_idx,
            "combined",
            rows_map,
            has_pcr_data,
            has_pcr_interval=has_pcr_interval,
        )

    for i, m in enumerate(builder.meta):
        fig.data[i].visible = m["program"] == default_program

    has_negative_pts = _meta_has_negative_pts(builder.meta)
    pts_y_kw = _pts_yaxis_kwargs(has_negative_pts)

    fig.update_layout(
        template="plotly_white",
        autosize=True,
        height=760,
        hovermode="closest",
        dragmode=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            x=0,
            xanchor="left",
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#e2e8f0",
            borderwidth=1,
            font=dict(size=10),
            itemdoubleclick=False,
        ),
        margin=dict(l=56, r=24, t=48, b=48),
        paper_bgcolor="#f1f5f9",
        plot_bgcolor="#ffffff",
        uirevision="streampts-combined",
    )

    nrows = len(titles)
    unit = unit_label(default_unit)
    for r in range(1, nrows + 1):
        fig.update_xaxes(showgrid=True, gridcolor="#e2e8f0", row=r, col=1)
        fig.update_yaxes(showgrid=True, gridcolor="#e2e8f0", row=r, col=1)

    fig.update_xaxes(title_text=_xaxis_title(analysis), row=nrows, col=1)
    fig.update_yaxes(
        title_text=f"Video(蓝) / Audio(红) — {unit}",
        row=1,
        col=1,
        secondary_y=False,
        **pts_y_kw,
    )
    if has_pcr_data:
        fig.update_yaxes(
            title_text=f"PCR(绿) — {unit}",
            row=1,
            col=1,
            secondary_y=True,
            showgrid=False,
            **pts_y_kw,
        )
    fig.update_yaxes(title_text="ms", row=2, col=1)
    if has_pcr_interval:
        fig.update_yaxes(title_text="ms", row=3, col=1)

    return fig, builder.meta, has_negative_pts


def build_separate_figure_for_program(
    ps: ProgramSeries,
    diag: DiagnosticsResult,
    streams: list[StreamInfo],
    default_unit: UnitName,
    prog_idx: int,
    has_pcr_data: bool,
    has_pcr_interval: bool,
) -> tuple[go.Figure, list[dict], bool, int]:
    plan = _separate_row_plan(ps, streams, has_pcr_data, has_pcr_interval, diag)
    titles = [p.title for p in plan] or ["PTS"]
    nrows = len(titles)
    total = float(nrows)
    fig = make_subplots(
        rows=nrows,
        cols=1,
        shared_xaxes=True,
        shared_yaxes=False,
        vertical_spacing=0.03,
        row_heights=[1.0 / total] * nrows,
        subplot_titles=[f"<b>{t}</b>" for t in titles],
    )
    builder = _FigureBuilder(fig)
    _add_program_traces(
        builder,
        ps,
        diag,
        streams,
        default_unit,
        prog_idx,
        "separate",
        {},
        has_pcr_data,
        separate_plan=plan,
        has_pcr_interval=has_pcr_interval,
    )

    has_negative_pts = _meta_has_negative_pts(builder.meta)
    pts_y_kw = _pts_yaxis_kwargs(has_negative_pts)
    height = max(320, min(1400, 120 * nrows + 80))
    unit = unit_label(default_unit)

    fig.update_layout(
        template="plotly_white",
        autosize=True,
        height=height,
        hovermode="closest",
        dragmode=False,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            x=0,
            font=dict(size=9),
        ),
        margin=dict(l=56, r=24, t=48, b=48),
        paper_bgcolor="#f1f5f9",
        plot_bgcolor="#ffffff",
        uirevision=f"streampts-separate-{prog_idx}",
    )

    for p in plan:
        fig.update_xaxes(showgrid=True, gridcolor="#e2e8f0", row=p.row, col=1)
        fig.update_yaxes(showgrid=True, gridcolor="#e2e8f0", row=p.row, col=1)
        if p.kind in ("video", "audio"):
            fig.update_yaxes(title_text=f"{unit}", row=p.row, col=1, **pts_y_kw)
        elif p.kind == "pcr":
            fig.update_yaxes(title_text=f"PCR — {unit}", row=p.row, col=1, **pts_y_kw)
        elif p.kind in ("av", "pcr_interval"):
            fig.update_yaxes(title_text="ms", row=p.row, col=1)

    x_title = "Timeline (s)" if _program_uses_timeline(ps) else "Time (s)"
    fig.update_xaxes(title_text=x_title, row=nrows, col=1)
    return fig, builder.meta, has_negative_pts, height


def _program_options(analysis: AnalysisResult) -> list[dict]:
    return [
        {
            "index": i,
            "label": (
                f"Program {ps.program_id}"
                if ps.program_id is not None
                else "All streams"
            ),
        }
        for i, ps in enumerate(analysis.program_series)
    ]


def _programs_stream_catalog(analysis: AnalysisResult) -> list[dict]:
    catalog = []
    for i, ps in enumerate(analysis.program_series):
        streams: list[dict] = []
        for vidx in sorted(ps.video_streams.keys()):
            streams.append(
                {
                    "index": vidx,
                    "kind": "video",
                    "label": _stream_label(analysis.streams, vidx),
                }
            )
        for aidx in sorted(ps.audio_streams.keys()):
            streams.append(
                {
                    "index": aidx,
                    "kind": "audio",
                    "label": _stream_label(analysis.streams, aidx),
                }
            )
        catalog.append(
            {
                "index": i,
                "program_id": ps.program_id,
                "streams": streams,
            }
        )
    return catalog


def build_controls_html(
    analysis: AnalysisResult, default_program: int, default_unit: UnitName = "us"
) -> str:
    has_pcr = any(ps.pcr_points for ps in analysis.program_series)
    options = "\n".join(
        f'<option value="{o["index"]}"{" selected" if o["index"] == default_program else ""}>'
        f'{o["label"]}</option>'
        for o in _program_options(analysis)
    )
    pcr_btn = (
        '<button type="button" data-filter="pcr">PCR</button>' if has_pcr else ""
    )
    pcr_hint = (
        '<span class="dot pcr"></span> PCR 绿' if has_pcr else ""
    )
    us_active = "active" if default_unit == "us" else ""
    k90_active = "active" if default_unit == "90k" else ""
    return f"""
<div class="chart-controls">
  <div class="ctrl-group">
    <label for="program-select">Program</label>
    <select id="program-select">{options}</select>
  </div>
  <div class="ctrl-group">
    <label for="stream-select">Stream</label>
    <select id="stream-select"><option value="all">全部 Stream</option></select>
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">PTS 单位</span>
    <div class="btn-group" id="unit-mode">
      <button type="button" class="{us_active}" data-unit="us">µs</button>
      <button type="button" class="{k90_active}" data-unit="90k">90k</button>
    </div>
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">布局</span>
    <div class="btn-group" id="layout-mode">
      <button type="button" class="active" data-layout="combined">同图</button>
      <button type="button" data-layout="separate">分开</button>
    </div>
  </div>
  <div class="ctrl-group">
    <span class="ctrl-label">显示</span>
    <div class="btn-group" id="stream-filter">
      <button type="button" class="active" data-filter="all">全部</button>
      <button type="button" data-filter="video">Video</button>
      <button type="button" data-filter="audio">Audio</button>
      {pcr_btn}
    </div>
  </div>
  <div class="legend-hint">
    <span class="dot video"></span> Video 蓝
    <span class="dot audio"></span> Audio 红
    {pcr_hint}
    <span class="dot jump"></span> 跳变前后 PTS
  </div>
</div>
"""


def build_summary_html(
    analysis: AnalysisResult,
    diagnostics_by_program: list[DiagnosticsResult],
    program_index: int = 0,
) -> str:
    diag = diagnostics_by_program[program_index]
    ps = analysis.program_series[program_index]
    prog = ps.program_id if ps.program_id is not None else "—"
    duration = format_time(analysis.duration or 0) if analysis.duration else "—"
    fname = Path(analysis.input_path).name

    video_count = sum(len(v) for v in ps.video_streams.values())
    audio_count = sum(len(a) for a in ps.audio_streams.values())
    pcr_count = len(ps.pcr_points)
    v_jumps = sum(
        len(d.jumps)
        for idx, d in diag.stream_diagnostics.items()
        if idx in ps.video_streams
    )
    a_jumps = sum(
        len(d.jumps)
        for idx, d in diag.stream_diagnostics.items()
        if idx in ps.audio_streams
    )
    backward = sum(d.backward_count for d in diag.stream_diagnostics.values())
    av_mean = f"{diag.av_stats.mean_ms:.2f} ms" if diag.av_stats else "N/A"
    av_max = f"{diag.av_stats.max_ms:.2f} ms" if diag.av_stats else "N/A"
    av_exceed = str(diag.av_stats.exceed_count) if diag.av_stats else "N/A"
    pcr_anomaly = str(diag.pcr_stats.anomaly_count) if diag.pcr_stats else "N/A"
    pcr_jitter = (
        f"{diag.pcr_stats.max_jitter_ms:.2f} ms" if diag.pcr_stats else "N/A"
    )

    notes = ""
    if analysis.downsampled:
        notes += '<div class="note">显示降采样数据 (LTTB)。可用 <code>--full</code> 或 <code>--range</code> 查看更细粒度。</div>'
    needs_display_cap = any(
        len(pts) > DISPLAY_MAX_POINTS
        for ps in analysis.program_series
        for pts in list(ps.video_streams.values()) + list(ps.audio_streams.values())
    )
    if needs_display_cap:
        notes += (
            f'<div class="note">图表交互最多显示 {DISPLAY_MAX_POINTS} 点/流 (WebGL)，'
            "缩放平移更流畅。</div>"
        )

    return f"""
<header class="header">
  <div class="header-top">
    <h1>Stream PTS Report</h1>
    <p class="filename">{fname}</p>
  </div>
  <div class="meta">
    <span><b>时长</b> {duration}</span>
    <span><b>格式</b> {analysis.format_name}</span>
    <span><b>Program</b> {prog}</span>
  </div>
  <div class="cards">
    <div class="card video"><h3>Video</h3><p class="val">{video_count}</p><p class="sub">跳变 {v_jumps}</p></div>
    <div class="card audio"><h3>Audio</h3><p class="val">{audio_count}</p><p class="sub">跳变 {a_jumps}</p></div>
    <div class="card pcr"><h3>PCR</h3><p class="val">{pcr_count}</p><p class="sub">异常 {pcr_anomaly}</p></div>
    <div class="card av"><h3>A/V Sync</h3><p class="val">{av_mean}</p><p class="sub">max {av_max}</p></div>
  </div>
  {notes}
  <div class="help">
    <b>操作：</b>默认以散点显示各 PTS · 可选 Program / Stream · 分开布局按 Stream 分行 · 多段重复 PTS 时 X 轴为连续 Timeline · 滚轮缩放 · 左/右键平移
  </div>
</header>
"""


HTML_STYLE = """
:root { --video: #2563eb; --audio: #dc2626; --pcr: #16a34a; }
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #e2e8f0; color: #1e293b; display: flex; flex-direction: column; min-height: 100vh; }
.header { background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%); color: #f8fafc; padding: 20px 24px 14px; }
.header-top h1 { margin: 0; font-size: 1.5rem; }
.filename { margin: 4px 0 12px; color: #94a3b8; font-size: 0.95rem; }
.meta { display: flex; flex-wrap: wrap; gap: 20px; font-size: 0.9rem; margin-bottom: 14px; }
.meta b { color: #cbd5e1; margin-right: 6px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 10px; }
.card { background: rgba(255,255,255,0.08); border-radius: 8px; padding: 10px 12px; border-left: 4px solid #64748b; }
.card.video { border-left-color: var(--video); }
.card.audio { border-left-color: var(--audio); }
.card.pcr { border-left-color: var(--pcr); }
.card.av { border-left-color: #0891b2; }
.card h3 { margin: 0 0 4px; font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; }
.card .val { margin: 0; font-size: 1.3rem; font-weight: 700; }
.card .sub { margin: 2px 0 0; font-size: 0.78rem; color: #94a3b8; }
.note { background: rgba(255,255,255,0.1); border-radius: 6px; padding: 6px 10px; font-size: 0.85rem; margin-bottom: 6px; }
.help { font-size: 0.8rem; color: #94a3b8; }
.chart-wrap { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; margin: 12px 16px 16px; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(15,23,42,0.08); overflow: hidden; }
.chart-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 20px; padding: 12px 16px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }
.ctrl-group { display: flex; align-items: center; gap: 8px; }
.ctrl-group label, .ctrl-label { font-size: 0.85rem; font-weight: 600; color: #475569; white-space: nowrap; }
#program-select { padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.9rem; min-width: 130px; }
#stream-select { padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.9rem; min-width: 180px; max-width: 320px; }
.btn-group { display: flex; gap: 4px; flex-wrap: wrap; }
.btn-group button { padding: 6px 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; cursor: pointer; font-size: 0.85rem; color: #334155; }
.btn-group button:hover { background: #f1f5f9; }
.btn-group button.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.legend-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 0.78rem; color: #64748b; margin-left: auto; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 3px; vertical-align: middle; }
.dot.video { background: var(--video); }
.dot.audio { background: var(--audio); }
.dot.pcr { background: var(--pcr); }
.dot.jump { background: #fef3c7; border: 2px solid #f97316; width: 11px; height: 11px; border-radius: 2px; }
.plot-panel { flex: 1 1 auto; width: 100%; min-height: 320px; display: flex; flex-direction: column; }
.plot-panel.hidden { display: none; }
#plot-combined-wrap,
#plot-separate-wrap { width: 100%; flex: 1 1 0; min-height: 0; }
#streampts-plot-combined,
#streampts-plot-separate { flex: 1 1 auto; width: 100% !important; max-width: 100%; height: 100% !important; min-height: 320px; }
.plot-panel .js-plotly-plot,
.plot-panel .plotly-graph-div { width: 100% !important; max-width: 100%; height: 100% !important; }
"""


def _control_script(
    meta_combined: list[dict],
    meta_separate_by_program: dict[str, list[dict]],
    programs_catalog: list[dict],
    separate_heights: dict[str, int],
    default_program: int,
    has_pcr_data: bool,
    has_negative_pts: bool,
    default_unit: UnitName = "us",
) -> str:
    initial_unit = default_unit if default_unit in ("us", "90k") else "us"
    return f"""
<script>
(function() {{
  var META = {{
    combined: {json.dumps(meta_combined)},
    separate: {json.dumps(meta_separate_by_program)}
  }};
  var PROGRAMS = {json.dumps(programs_catalog)};
  var SEPARATE_HEIGHTS = {json.dumps(separate_heights)};
  var HAS_PCR = {json.dumps(has_pcr_data)};
  var HAS_NEGATIVE_PTS = {json.dumps(has_negative_pts)};
  var US_TO_90K = {US_TO_90K};
  var K90_TO_US = {K90_TO_US};
  var currentProgram = {default_program};
  var currentStream = 'all';
  var currentFilter = 'all';
  var currentLayout = 'combined';
  var currentUnit = {json.dumps(initial_unit)};
  var previousUnit = currentUnit;
  var plotSynced = {{ combined: false, separate: false }};
  var combinedPlotBuilt = false;
  var separatePlotBuilt = false;
  var separatePlotProgram = -1;

  function activePlotKey() {{
    return currentLayout;
  }}

  function plotEl(key) {{
    return document.getElementById('streampts-plot-' + key);
  }}

  function separateMeta() {{
    return META.separate[String(currentProgram)] || [];
  }}

  function activeMeta() {{
    return currentLayout === 'separate' ? separateMeta() : META.combined;
  }}

  function kindsForFilter(filter) {{
    if (filter === 'video') return ['video', 'jump_video', 'jump_link_video'];
    if (filter === 'audio') return ['audio', 'jump_audio', 'jump_link_audio'];
    if (filter === 'pcr') return ['pcr'];
    var all = ['video', 'audio', 'jump_video', 'jump_audio', 'jump_link_video', 'jump_link_audio'];
    if (HAS_PCR) all.push('pcr');
    return all;
  }}

  function matchesStream(m) {{
    if (currentStream === 'all') return true;
    var si = parseInt(currentStream, 10);
    if (m.stream_index === undefined || m.stream_index === null) return false;
    return m.stream_index === si;
  }}

  function computeVisibilitySeparate(meta) {{
    return meta.map(function(m) {{
      if (currentStream !== 'all') {{
        if (m.kind === 'av' || m.kind === 'pcr_interval' || m.kind === 'pcr') return false;
        return matchesStream(m);
      }}
      if (m.kind === 'av' || m.kind === 'pcr_interval' || m.kind === 'pcr') return true;
      return true;
    }});
  }}

  function computeVisibilityCombined(meta) {{
    var kinds = kindsForFilter(currentFilter);
    return meta.map(function(m) {{
      if (m.kind === 'av' || m.kind === 'pcr_interval') return m.program === currentProgram;
      if (m.program !== currentProgram) return false;
      if (currentStream !== 'all' && !matchesStream(m)) return false;
      return kinds.indexOf(m.kind) >= 0;
    }});
  }}

  function computeVisibility(meta) {{
    if (currentLayout === 'separate') return computeVisibilitySeparate(meta);
    return computeVisibilityCombined(meta);
  }}

  function updateStreamSelect() {{
    var sel = document.getElementById('stream-select');
    if (!sel) return;
    var prog = PROGRAMS[currentProgram];
    var html = '<option value="all">全部 Stream</option>';
    if (prog && prog.streams) {{
      prog.streams.forEach(function(s) {{
        html += '<option value="' + s.index + '">' + s.label + '</option>';
      }});
    }}
    sel.innerHTML = html;
    sel.value = currentStream;
    if (sel.selectedIndex < 0) {{
      currentStream = 'all';
      sel.value = 'all';
    }}
  }}

  function updateSeparateAxisVisibility(gd, meta, visible) {{
    if (!gd || !gd.layout) return;
    var rows = {{}};
    meta.forEach(function(m, i) {{
      if (!rows[m.row]) rows[m.row] = false;
      if (visible[i]) rows[m.row] = true;
    }});
    var rel = {{}};
    Object.keys(rows).forEach(function(row) {{
      var r = parseInt(row, 10);
      var suffix = r <= 1 ? '' : r;
      var show = rows[row];
      rel['yaxis' + suffix + '.visible'] = show;
      rel['xaxis' + suffix + '.visible'] = show;
    }});
    if (Object.keys(rel).length) Plotly.relayout(gd, rel);
  }}

  function unitLabel(u) {{
    return u === 'us' ? 'PTS (µs)' : 'PTS (90k)';
  }}

  function ptsAxisKeys(gd, meta, key) {{
    if (key === 'combined') {{
      return HAS_PCR ? ['yaxis', 'yaxis2'] : ['yaxis'];
    }}
    var rows = {{}};
    meta.forEach(function(m) {{
      if (m.pts_pairs || m.jumps) rows[m.row] = true;
    }});
    return Object.keys(rows).map(function(row) {{
      var r = parseInt(row, 10);
      return r <= 1 ? 'yaxis' : 'yaxis' + r;
    }});
  }}

  function unitFactor(fromUnit, toUnit) {{
    if (fromUnit === toUnit) return 1;
    if (fromUnit === 'us' && toUnit === '90k') return US_TO_90K;
    if (fromUnit === '90k' && toUnit === 'us') return K90_TO_US;
    return 1;
  }}

  function transformRange(range, fromUnit, toUnit) {{
    if (!range || range.length !== 2) return null;
    var f = unitFactor(fromUnit, toUnit);
    var nr = [range[0] * f, range[1] * f];
    if (!HAS_NEGATIVE_PTS && nr[0] < 0) nr[0] = 0;
    return nr;
  }}

  function markOtherPlotStale() {{
    var other = activePlotKey() === 'combined' ? 'separate' : 'combined';
    plotSynced[other] = false;
  }}

  function yFromPairs(pairs, unit) {{
    if (unit === 'us') {{
      return pairs.map(function(p) {{ return Math.round(p[0] * 1000000); }});
    }}
    return pairs.map(function(p) {{ return p[1]; }});
  }}

  function jumpLinkY(jumps, unit) {{
    var y = [];
    jumps.forEach(function(j) {{
      y.push(unit === 'us' ? Math.round(j[0] * 1000000) : j[1]);
      y.push(unit === 'us' ? Math.round(j[2] * 1000000) : j[3]);
      y.push(null);
    }});
    return y;
  }}

  function jumpMarkerY(jumps, unit) {{
    var y = [];
    jumps.forEach(function(j) {{
      y.push(unit === 'us' ? Math.round(j[0] * 1000000) : j[1]);
      y.push(unit === 'us' ? Math.round(j[2] * 1000000) : j[3]);
    }});
    return y;
  }}

  function applyUnitToPlot(gd, key, fromUnit) {{
    if (!gd || !gd.data) return;
    var meta = key === 'separate' ? separateMeta() : META.combined;
    var ys = [], yIdx = [], texts = [], tIdx = [];
    meta.forEach(function(m, i) {{
      if (m.pts_pairs) {{
        ys.push(yFromPairs(m.pts_pairs, currentUnit));
        yIdx.push(i);
      }}
      if (m.jumps) {{
        if (m.jump_kind === 'link') {{
          ys.push(jumpLinkY(m.jumps, currentUnit));
          yIdx.push(i);
        }} else if (m.jump_kind === 'marker') {{
          var markerY = jumpMarkerY(m.jumps, currentUnit);
          ys.push(markerY);
          texts.push(markerY.map(String));
          yIdx.push(i);
          tIdx.push(i);
        }}
      }}
    }});

    var rel = {{}};
    if (key === 'combined') {{
      var ul = unitLabel(currentUnit);
      rel['yaxis.title.text'] = 'Video(蓝) / Audio(红) — ' + ul;
      if (HAS_PCR) rel['yaxis2.title.text'] = 'PCR(绿) — ' + ul;
    }}

    ptsAxisKeys(gd, meta, key).forEach(function(axKey) {{
      var ax = gd.layout[axKey];
      if (ax && ax.range) {{
        var nr = transformRange(ax.range, fromUnit, currentUnit);
        if (nr) rel[axKey + '.range'] = nr;
      }}
    }});

    if (yIdx.length) Plotly.restyle(gd, {{ y: ys }}, yIdx);
    if (tIdx.length) Plotly.restyle(gd, {{ text: texts }}, tIdx);
    if (Object.keys(rel).length) Plotly.relayout(gd, rel);
  }}

  function syncPlot(key, opts) {{
    opts = opts || {{}};
    var gd = plotEl(key);
    if (!gd || !gd.data) return;
    var meta = key === 'separate' ? separateMeta() : META.combined;
    var vis = computeVisibility(meta);

    function afterVisibility() {{
      if (key === 'separate') updateSeparateAxisVisibility(gd, meta, vis);
      if (opts.unit) applyUnitToPlot(gd, key, opts.fromUnit || previousUnit);
    }}

    if (opts.visibility !== false) {{
      Plotly.restyle(gd, {{ visible: vis }}).then(afterVisibility);
    }} else {{
      afterVisibility();
    }}
    plotSynced[key] = true;
  }}

  function applyVisibility() {{
    syncPlot(activePlotKey(), {{ unit: false }});
    markOtherPlotStale();
  }}

  function applyUnitSwitch() {{
    var key = activePlotKey();
    var fromUnit = previousUnit;
    previousUnit = currentUnit;
    syncPlot(key, {{ visibility: false, unit: true, fromUnit: fromUnit }});
    markOtherPlotStale();
  }}

  function plotWrapEl(key) {{
    return document.getElementById(key === 'combined' ? 'plot-combined-wrap' : 'plot-separate-wrap');
  }}

  function separateMinHeight() {{
    return SEPARATE_HEIGHTS[String(currentProgram)] || 320;
  }}

  function availablePlotHeight(key) {{
    var controls = document.querySelector('.chart-controls');
    var avail = window.innerHeight - 24;
    if (controls) {{
      avail = window.innerHeight - controls.getBoundingClientRect().bottom - 16;
    }}
    avail = Math.max(320, Math.floor(avail));
    if (key === 'separate') {{
      return Math.max(separateMinHeight(), avail);
    }}
    return avail;
  }}

  function plotTargetHeight(key) {{
    var wrap = plotWrapEl(key);
    if (wrap && !wrap.classList.contains('hidden')) {{
      var wh = wrap.clientHeight;
      if (wh >= 320) return wh;
    }}
    return availablePlotHeight(key);
  }}

  function resizePlot(key) {{
    var gd = plotEl(key);
    if (!gd || !gd.layout) return;
    var h = plotTargetHeight(key);
    gd.style.height = h + 'px';
    var rel = Plotly.relayout(gd, {{ height: h, autosize: true }});
    var done = function() {{ Plotly.Plots.resize(gd); }};
    if (rel && rel.then) rel.then(done);
    else done();
  }}

  function ensureCombinedPlot(callback) {{
    if (combinedPlotBuilt) {{
      if (callback) callback();
      return;
    }}
    var spec = window.STREAMPTS_COMBINED_SPEC;
    if (!spec) {{
      if (callback) callback();
      return;
    }}
    var h = plotTargetHeight('combined');
    if (h < 320) h = availablePlotHeight('combined');
    var layout = JSON.parse(JSON.stringify(spec.layout));
    layout.autosize = true;
    layout.height = h;
    delete layout.width;
    Plotly.newPlot(
      'streampts-plot-combined',
      spec.data,
      layout,
      window.STREAMPTS_PLOT_CONFIG || {{}}
    ).then(function() {{
      combinedPlotBuilt = true;
      setupPlotInteraction(plotEl('combined'));
      resizePlot('combined');
      if (callback) callback();
    }});
  }}

  function ensureSeparatePlot(callback) {{
    if (separatePlotBuilt && separatePlotProgram === currentProgram) {{
      if (callback) callback();
      return;
    }}
    var spec = window.STREAMPTS_SEPARATE_SPECS[String(currentProgram)];
    if (!spec) {{
      if (callback) callback();
      return;
    }}
    var plotHost = document.getElementById('streampts-plot-separate');
    var h = plotTargetHeight('separate');
    if (h < 320) h = availablePlotHeight('separate');
    if (plotHost) plotHost.style.height = h + 'px';
    var existing = plotEl('separate');
    if (existing && existing.data) Plotly.purge(existing);
    requestAnimationFrame(function() {{
      requestAnimationFrame(function() {{
        var layout = JSON.parse(JSON.stringify(spec.layout));
        layout.autosize = true;
        layout.height = h;
        delete layout.width;
        Plotly.newPlot(
          'streampts-plot-separate',
          spec.data,
          layout,
          window.STREAMPTS_PLOT_CONFIG || {{}}
        ).then(function() {{
          separatePlotBuilt = true;
          separatePlotProgram = currentProgram;
          setupPlotInteraction(plotEl('separate'));
          resizePlot('separate');
          if (callback) callback();
        }});
      }});
    }});
  }}

  function setLayout(mode) {{
    currentLayout = mode;
    document.getElementById('plot-combined-wrap').classList.toggle('hidden', mode !== 'combined');
    document.getElementById('plot-separate-wrap').classList.toggle('hidden', mode !== 'separate');

    function finishSync() {{
      if (!plotSynced[mode]) {{
        syncPlot(mode, {{ unit: true, fromUnit: previousUnit }});
      }} else {{
        syncPlot(mode, {{ unit: false }});
      }}
      requestAnimationFrame(function() {{
        requestAnimationFrame(function() {{
          resizePlot(mode);
        }});
      }});
    }}

    if (mode === 'separate') {{
      ensureSeparatePlot(finishSync);
    }} else {{
      finishSync();
    }}
  }}

  function setupPlotInteraction(gd) {{
    if (!gd || gd._streamptsInteraction) return;
    gd._streamptsInteraction = true;

    function xAxes() {{
      var keys = [];
      for (var k in gd.layout) {{
        if (k === 'xaxis' || /^xaxis\\d+$/.test(k)) keys.push(k);
      }}
      return keys.sort();
    }}

    function plotWidth() {{
      var size = gd._fullLayout && gd._fullLayout._size;
      return (size && size.w) ? size.w : (gd.offsetWidth || 800);
    }}

    // Gentle wheel zoom on time axis; coalesce events per frame to avoid lag/inertia.
    var wheelAccum = 0;
    var wheelRaf = null;
    var wheelAnchorX = 0.5;
    var relayoutBusy = false;
    var WHEEL_ZOOM_BASE = 0.975;

    function scheduleWheel() {{
      if (wheelRaf) return;
      wheelRaf = requestAnimationFrame(applyWheelZoom);
    }}

    function applyWheelZoom() {{
      wheelRaf = null;
      if (!wheelAccum) return;
      if (relayoutBusy) {{
        scheduleWheel();
        return;
      }}

      var delta = wheelAccum;
      wheelAccum = 0;

      var xa = gd.layout.xaxis;
      if (!xa || !xa.range) return;
      var xr = xa.range.slice();
      var span = xr[1] - xr[0];
      if (span <= 0) return;

      var steps = -delta / 53;
      var factor = Math.pow(WHEEL_ZOOM_BASE, steps);
      var newSpan = span * factor;
      var xCenter = xr[0] + wheelAnchorX * span;
      var nx0 = xCenter - wheelAnchorX * newSpan;
      var nx1 = nx0 + newSpan;

      var update = {{}};
      xAxes().forEach(function(k) {{
        update[k + '.range[0]'] = nx0;
        update[k + '.range[1]'] = nx1;
      }});

      relayoutBusy = true;
      Plotly.relayout(gd, update).finally(function() {{
        relayoutBusy = false;
        if (wheelAccum) scheduleWheel();
      }});
    }}

    gd.addEventListener('wheel', function(e) {{
      e.preventDefault();
      e.stopPropagation();
      var rect = gd.getBoundingClientRect();
      wheelAnchorX = rect.width > 0
        ? Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
        : 0.5;
      wheelAccum += e.deltaY;
      scheduleWheel();
    }}, {{ passive: false }});

    // Right-button pan: one update per frame; cancel pending frame on release.
    var panning = false, startX = 0, startRanges = {{}}, panRaf = null;

    function applyPan(dx) {{
      if (!panning) return;
      var plotW = plotWidth();
      var update = {{}};
      xAxes().forEach(function(k) {{
        var r = startRanges[k];
        if (!r) return;
        var span = r[1] - r[0];
        var shift = -dx / plotW * span;
        update[k + '.range[0]'] = r[0] + shift;
        update[k + '.range[1]'] = r[1] + shift;
      }});
      if (Object.keys(update).length) Plotly.relayout(gd, update);
    }}

    gd.addEventListener('mousedown', function(e) {{
      if (e.button !== 0 && e.button !== 2) return;
      if (e.button === 2) e.preventDefault();
      panning = true;
      startX = e.clientX;
      startRanges = {{}};
      xAxes().forEach(function(k) {{
        var ax = gd.layout[k];
        if (ax && ax.range) startRanges[k] = ax.range.slice();
      }});
    }});
    window.addEventListener('mousemove', function(e) {{
      if (!panning) return;
      var dx = e.clientX - startX;
      if (panRaf) cancelAnimationFrame(panRaf);
      panRaf = requestAnimationFrame(function() {{
        panRaf = null;
        applyPan(dx);
      }});
    }});
    window.addEventListener('mouseup', function(e) {{
      if (e.button !== 0 && e.button !== 2) return;
      panning = false;
      if (panRaf) {{
        cancelAnimationFrame(panRaf);
        panRaf = null;
      }}
    }});
  }}

  function setupControls() {{
    updateStreamSelect();
    document.getElementById('program-select').addEventListener('change', function(e) {{
      currentProgram = parseInt(e.target.value, 10);
      currentStream = 'all';
      updateStreamSelect();
      separatePlotBuilt = false;
      separatePlotProgram = -1;
      if (currentLayout === 'separate') {{
        setLayout('separate');
      }} else {{
        applyVisibility();
      }}
    }});
    document.getElementById('stream-select').addEventListener('change', function(e) {{
      currentStream = e.target.value;
      applyVisibility();
    }});
    document.querySelectorAll('#unit-mode button').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        document.querySelectorAll('#unit-mode button').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
        currentUnit = btn.getAttribute('data-unit');
        applyUnitSwitch();
      }});
    }});
    document.querySelectorAll('#layout-mode button').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        document.querySelectorAll('#layout-mode button').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
        setLayout(btn.getAttribute('data-layout'));
      }});
    }});
    document.querySelectorAll('#stream-filter button').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        document.querySelectorAll('#stream-filter button').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
        currentFilter = btn.getAttribute('data-filter');
        applyVisibility();
      }});
    }});
  }}

  function waitForPlotly(tries) {{
    if (typeof Plotly === 'undefined') {{
      if (tries < 100) setTimeout(function() {{ waitForPlotly(tries + 1); }}, 50);
      return;
    }}
    ensureCombinedPlot(function() {{
      syncPlot('combined', {{ unit: true, fromUnit: currentUnit }});
    }});
  }}

  function init() {{
    setupControls();
    waitForPlotly(0);
    var resizeTimer = null;
    window.addEventListener('resize', function() {{
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function() {{
        resizePlot(activePlotKey());
      }}, 150);
    }});
  }}

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}})();
</script>
"""


def generate_report_html(
    analysis: AnalysisResult,
    config: AppConfig,
    *,
    default_program: int = 0,
    default_unit: UnitName = "us",
) -> str:
    diagnostics_by_program = [
        run_diagnostics(ps, analysis.streams, config) for ps in analysis.program_series
    ]
    has_pcr_data = any(ps.pcr_points for ps in analysis.program_series)
    has_pcr_interval = any(d.pcr_intervals for d in diagnostics_by_program)
    fig_c, meta_c, has_neg_c = build_figure(
        analysis, diagnostics_by_program, config, "combined", default_unit, default_program
    )
    fig_c_json = fig_c.to_json()
    if not fig_c_json:
        raise ValueError("同图布局图表序列化失败")
    combined_spec = json.loads(fig_c_json)
    separate_specs: dict[str, dict] = {}
    meta_separate: dict[str, list] = {}
    separate_heights: dict[str, int] = {}
    for i, (ps, diag) in enumerate(
        zip(analysis.program_series, diagnostics_by_program)
    ):
        fig_s, meta_s, _, height = build_separate_figure_for_program(
            ps,
            diag,
            analysis.streams,
            default_unit,
            i,
            has_pcr_data,
            has_pcr_interval,
        )
        fig_json = fig_s.to_json()
        if not fig_json:
            raise ValueError(f"节目 {i} 图表序列化失败")
        separate_specs[str(i)] = json.loads(fig_json)
        meta_separate[str(i)] = meta_s
        separate_heights[str(i)] = height
    has_negative_pts = has_neg_c or any(
        _meta_has_negative_pts(m) for m in meta_separate.values()
    )
    programs_catalog = _programs_stream_catalog(analysis)
    summary = build_summary_html(analysis, diagnostics_by_program, default_program)
    controls = build_controls_html(analysis, default_program, default_unit)
    plot_c = """<div id="streampts-plot-combined" class="plotly-graph-div" style="width:100%;height:100%;"></div>"""
    combined_spec_json = json.dumps(combined_spec, separators=(",", ":"))
    separate_specs_json = json.dumps(separate_specs, separators=(",", ":"))
    plot_config_json = json.dumps(PLOT_CONFIG)
    plot_specs_script = f"""<script>
window.STREAMPTS_COMBINED_SPEC = {combined_spec_json};
window.STREAMPTS_SEPARATE_SPECS = {separate_specs_json};
window.STREAMPTS_PLOT_CONFIG = {plot_config_json};
</script>"""
    separate_panel = f"""<div id="plot-separate-wrap" class="plot-panel hidden">
  <div id="streampts-plot-separate" class="plotly-graph-div" style="width:100%;height:100%;"></div>
</div>"""
    fname = Path(analysis.input_path).name
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Stream PTS — {fname}</title>
  <style>{HTML_STYLE}</style>
  {_plotly_cdn_tag()}
</head>
<body>
{summary}
<div class="chart-wrap">
{controls}
<div id="plot-combined-wrap" class="plot-panel">{plot_c}</div>
{separate_panel}
</div>
{plot_specs_script}
{_control_script(meta_c, meta_separate, programs_catalog, separate_heights, default_program, has_pcr_data, has_negative_pts, default_unit)}
</body>
</html>
"""
