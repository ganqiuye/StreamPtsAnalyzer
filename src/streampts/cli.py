from __future__ import annotations

import argparse
import sys
from pathlib import Path

from streampts.analyze_service import AnalyzeError, AnalyzeOptions, run_analyze


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="streampts",
        description="Analyze presentation timestamps with ffprobe and generate interactive HTML reports.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a media file and generate HTML report")
    analyze.add_argument("input", type=Path, help="Input media file (.ts, .avi, .mkv, .mp4, …)")
    analyze.add_argument("-o", "--output", type=Path, help="Output HTML path")
    analyze.add_argument("--program", type=int, default=0, help="Default program index (0-based)")
    analyze.add_argument("--range", dest="time_range", help="Time range START-END, e.g. 00:10:00-00:20:00")
    analyze.add_argument("--full", action="store_true", help="Force full packet parse")
    analyze.add_argument("--unit", choices=["90k", "us", "ms", "sec"], default="us")
    analyze.add_argument("--open", action="store_true", help="Open report in browser")
    analyze.add_argument("--ffprobe-path", help="Path to ffprobe executable")
    analyze.add_argument("--jump-min-ms", type=float, help="Jump detection minimum delta (ms)")
    analyze.add_argument("--jump-factor", type=float, help="Jump relative factor vs median delta")
    analyze.add_argument("--jump-max-ms", type=float, help="Jump maximum delta (ms)")
    analyze.add_argument("--annotate-top", type=int, help="Max jump labels on chart")
    analyze.add_argument("--av-threshold-ms", type=float, help="A/V sync alert threshold (ms)")
    analyze.add_argument("--threshold-mb", type=float, help="File size MB threshold for downsampling")
    analyze.add_argument("--timeout", type=int, help="ffprobe timeout in seconds")
    analyze.add_argument("--verbose", action="store_true")

    return parser.parse_args(argv)


def _options_from_args(args: argparse.Namespace) -> AnalyzeOptions:
    return AnalyzeOptions(
        input=args.input,
        output=args.output,
        program=args.program,
        time_range=args.time_range,
        force_full=args.full,
        unit=args.unit,
        open_report=args.open,
        ffprobe_path=args.ffprobe_path,
        jump_min_ms=args.jump_min_ms,
        jump_factor=args.jump_factor,
        jump_max_ms=args.jump_max_ms,
        annotate_top=args.annotate_top,
        av_threshold_ms=args.av_threshold_ms,
        threshold_mb=args.threshold_mb,
        timeout=args.timeout,
        verbose=args.verbose,
    )


def analyze_command(args: argparse.Namespace) -> int:
    options = _options_from_args(args)

    def progress(message: str) -> None:
        print(message)

    try:
        run_analyze(options, progress=progress)
    except AnalyzeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "analyze":
        raise SystemExit(analyze_command(args))
    raise SystemExit(2)
