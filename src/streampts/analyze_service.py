from __future__ import annotations

import os
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from streampts.config import AppConfig, load_config
from streampts.extractor.ffprobe import FfprobeError, resolve_ffprobe
from streampts.models import UnitName

ProgressCallback = Callable[[str], None]


@dataclass
class AnalyzeOptions:
    input: Path
    output: Path | None = None
    program: int = 0
    time_range: str | None = None
    force_full: bool = False
    unit: UnitName = "us"
    open_report: bool = False
    ffprobe_path: str | None = None
    jump_min_ms: float | None = None
    jump_factor: float | None = None
    jump_max_ms: float | None = None
    annotate_top: int | None = None
    av_threshold_ms: float | None = None
    threshold_mb: float | None = None
    timeout: int | None = None
    verbose: bool = False


class AnalyzeError(Exception):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def default_output(input_path: Path) -> Path:
    return input_path.with_suffix(".pts-report.html")


def apply_options_to_config(config: AppConfig, options: AnalyzeOptions) -> AppConfig:
    if options.ffprobe_path:
        config.tools.ffprobe_path = options.ffprobe_path
    if options.jump_min_ms is not None:
        config.jump.min_ms = options.jump_min_ms
    if options.jump_factor is not None:
        config.jump.factor = options.jump_factor
    if options.jump_max_ms is not None:
        config.jump.max_ms = options.jump_max_ms
    if options.annotate_top is not None:
        config.jump.annotate_top = options.annotate_top
    if options.av_threshold_ms is not None:
        config.av_sync.threshold_ms = options.av_threshold_ms
    if options.threshold_mb is not None:
        config.threshold_mb = options.threshold_mb
    if options.timeout is not None:
        config.timeout = options.timeout
    config.default_unit = options.unit
    return config


def _notify(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def open_report_path(output_path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(output_path)  # type: ignore[attr-defined]
    else:
        webbrowser.open(output_path.as_uri())


def run_analyze(
    options: AnalyzeOptions,
    *,
    config: AppConfig | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    from streampts.extractor.parser import extract_analysis
    from streampts.report.plotly_builder import generate_report_html

    input_path = options.input.resolve()
    if not input_path.is_file():
        raise AnalyzeError(f"文件不存在: {input_path}", exit_code=2)

    cfg = apply_options_to_config(config or load_config(input_path.parent), options)
    try:
        ffprobe = resolve_ffprobe(cfg)
    except FfprobeError as exc:
        raise AnalyzeError(str(exc), exit_code=exc.exit_code) from exc

    _notify(progress, "正在提取并分析包数据…")
    try:
        analysis = extract_analysis(
            input_path,
            ffprobe,
            cfg,
            time_range=options.time_range,
            force_full=options.force_full,
            verbose=options.verbose,
            progress=progress,
        )
    except FfprobeError as exc:
        raise AnalyzeError(str(exc), exit_code=exc.exit_code) from exc

    program_index = options.program
    if program_index >= len(analysis.program_series):
        program_index = 0

    _notify(progress, "正在运行诊断…")
    _notify(progress, "正在生成报告…")
    html = generate_report_html(
        analysis,
        cfg,
        default_program=program_index,
        default_unit=options.unit,
    )

    output_path = options.output or default_output(input_path)
    output_path.write_text(html, encoding="utf-8")
    _notify(progress, f"报告已保存: {output_path}")

    if options.open_report:
        open_report_path(output_path)

    return output_path
