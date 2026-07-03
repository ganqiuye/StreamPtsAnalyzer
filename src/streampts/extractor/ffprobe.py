from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from streampts.config import AppConfig


class FfprobeError(Exception):
    def __init__(self, message: str, exit_code: int = 1, stderr: str = "") -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


def _is_windows() -> bool:
    return sys.platform == "win32"


def _subprocess_kwargs() -> dict:
    if not _is_windows():
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }


def resolve_ffprobe(config: AppConfig) -> str:
    if config.tools.ffprobe_path:
        path = Path(config.tools.ffprobe_path)
        if path.is_dir():
            path = path / ("ffprobe.exe" if _is_windows() else "ffprobe")
        if not path.is_file():
            raise FfprobeError(
                f"ffprobe not found at configured path: {path}", exit_code=2
            )
        return str(path)

    found = _find_ffprobe_on_path()
    if found:
        return found

    for candidate in _default_ffprobe_candidates():
        if candidate.is_file():
            return str(candidate)

    raise FfprobeError(
        "未找到 ffprobe。请安装 ffmpeg，或在界面中指定 ffprobe.exe 路径，"
        "或在 ~/.streampts.toml 中设置 [tools].ffprobe_path。",
        exit_code=2,
    )


def _find_ffprobe_on_path() -> str | None:
    import os
    import shutil

    found = shutil.which("ffprobe")
    if found:
        return found

    # GUI / PyInstaller 启动时 PATH 可能不完整，补充常见安装目录。
    extra_dirs = [
        Path(r"D:\tools\ffmpeg\bin"),
        Path(r"C:\ffmpeg\bin"),
        Path(r"C:\Program Files\ffmpeg\bin"),
    ]
    if _is_windows():
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                extra_dirs.append(Path(base) / "ffmpeg" / "bin")

    name = "ffprobe.exe" if _is_windows() else "ffprobe"
    for directory in extra_dirs:
        candidate = directory / name
        if candidate.is_file():
            return str(candidate)
    return None


def _default_ffprobe_candidates() -> list[Path]:
    names = ["ffprobe.exe", "ffprobe"] if _is_windows() else ["ffprobe"]
    candidates: list[Path] = []
    for name in names:
        candidates.append(Path(r"D:\tools\ffmpeg\bin") / name)
    return candidates


def parse_time_range(range_str: str) -> str:
    """Convert HH:MM:SS-HH:MM:SS to ffprobe -read_intervals format."""
    parts = range_str.strip().split("-", 1)
    if len(parts) != 2:
        raise FfprobeError(f"Invalid --range format: {range_str!r}. Use START-END like 00:10:00-00:20:00")

    def to_hms(text: str) -> str:
        text = text.strip()
        if text.count(":") == 2:
            return text
        if text.count(":") == 1:
            return f"00:{text}"
        return f"00:00:{text}"

    start = to_hms(parts[0])
    end = to_hms(parts[1])

    def secs(hms: str) -> float:
        h, m, s = hms.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    duration = secs(end) - secs(start)
    if duration <= 0:
        raise FfprobeError(f"Range end must be after start: {range_str}")
    dur_h = int(duration // 3600)
    dur_m = int((duration % 3600) // 60)
    dur_s = duration % 60
    dur_str = f"{dur_h:02d}:{dur_m:02d}:{dur_s:06.3f}".rstrip("0").rstrip(".")
    return f"{start}%%+#{dur_str}"


def run_ffprobe(
    ffprobe: str,
    input_path: Path,
    *,
    show_packets: bool = False,
    read_interval: str | None = None,
    timeout: int = 300,
    verbose: bool = False,
) -> dict:
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
    ]
    if show_packets:
        cmd += [
            "-show_packets",
            "-show_entries",
            "packet=pts,pts_time,dts,dts_time,best_effort_timestamp,best_effort_timestamp_time,pcr,pcr_time,stream_index,flags",
        ]
    else:
        cmd += ["-show_programs", "-show_streams", "-show_format"]

    if read_interval:
        cmd += ["-read_intervals", read_interval]

    cmd.append(str(input_path))

    if verbose:
        print("Running:", " ".join(cmd))

    run_kwargs = _subprocess_kwargs()

    try:
        if show_packets:
            text, stderr_text = _run_ffprobe_to_tempfile(cmd, timeout=timeout, run_kwargs=run_kwargs)
        else:
            text, stderr_text = _run_ffprobe_capture(cmd, timeout=timeout, run_kwargs=run_kwargs)
    except subprocess.TimeoutExpired as exc:
        raise FfprobeError(
            f"ffprobe 超时（{timeout}s），可尝试缩小时间范围或增大超时设置",
            exit_code=3,
        ) from exc

    if not text.strip():
        hint = stderr_text.strip() or "无 stderr 输出"
        raise FfprobeError(
            "ffprobe 未返回 JSON 数据。请检查片源文件是否有效，以及 ffprobe 路径是否正确。\n"
            f"详情: {hint}",
            exit_code=3,
            stderr=stderr_text,
        )

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FfprobeError(
            f"ffprobe JSON 解析失败: {exc}",
            exit_code=3,
            stderr=stderr_text,
        ) from exc


def _decode_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _check_ffprobe_result(returncode: int, stderr_text: str) -> None:
    if returncode != 0:
        detail = stderr_text.strip() or f"exit code {returncode}"
        raise FfprobeError(
            f"ffprobe 执行失败: {detail}",
            exit_code=3,
            stderr=stderr_text,
        )


def _run_ffprobe_capture(
    cmd: list[str],
    *,
    timeout: int,
    run_kwargs: dict,
) -> tuple[str, str]:
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        **run_kwargs,
    )
    stderr_text = _decode_output(proc.stderr)
    _check_ffprobe_result(proc.returncode, stderr_text)
    return _decode_output(proc.stdout), stderr_text


def _run_ffprobe_to_tempfile(
    cmd: list[str],
    *,
    timeout: int,
    run_kwargs: dict,
) -> tuple[str, str]:
    import tempfile

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".json") as tmp:
            tmp_path = tmp.name
        with open(tmp_path, "wb") as out_file:
            proc = subprocess.run(
                cmd,
                stdout=out_file,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
                **run_kwargs,
            )
        stderr_text = _decode_output(proc.stderr)
        _check_ffprobe_result(proc.returncode, stderr_text)
        text = Path(tmp_path).read_text(encoding="utf-8", errors="replace")
        return text, stderr_text
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
