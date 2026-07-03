from __future__ import annotations

import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from streampts.models import UnitName


@dataclass
class JumpConfig:
    min_ms: float = 40.0
    factor: float = 10.0
    max_ms: float | None = 5000.0
    annotate_top: int = 20


@dataclass
class AvSyncConfig:
    threshold_ms: float = 40.0


@dataclass
class PcrConfig:
    interval_min_ms: float = 10.0
    interval_max_ms: float = 100.0


@dataclass
class ToolsConfig:
    ffprobe_path: str = ""


@dataclass
class AppConfig:
    jump: JumpConfig = None  # type: ignore[assignment]
    av_sync: AvSyncConfig = None  # type: ignore[assignment]
    pcr: PcrConfig = None  # type: ignore[assignment]
    tools: ToolsConfig = None  # type: ignore[assignment]
    threshold_mb: float = 100.0
    timeout: int = 300
    max_points: int = 5000
    default_unit: UnitName = "us"

    def __post_init__(self) -> None:
        if self.jump is None:
            self.jump = JumpConfig()
        if self.av_sync is None:
            self.av_sync = AvSyncConfig()
        if self.pcr is None:
            self.pcr = PcrConfig()
        if self.tools is None:
            self.tools = ToolsConfig()


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge_section(section_cls: type, base: Any, data: dict[str, Any]) -> Any:
    if not data:
        return base
    kwargs = {}
    for f in fields(section_cls):
        if f.name in data:
            kwargs[f.name] = data[f.name]
    return section_cls(**{**base.__dict__, **kwargs})


def load_config(cwd: Path | None = None) -> AppConfig:
    cfg = AppConfig()
    user_path = Path.home() / ".streampts.toml"
    project_path = (cwd or Path.cwd()) / ".streampts.toml"

    for path in (user_path, project_path):
        raw = _load_toml(path)
        if "jump" in raw:
            cfg.jump = _merge_section(JumpConfig, cfg.jump, raw["jump"])
        if "av_sync" in raw:
            cfg.av_sync = _merge_section(AvSyncConfig, cfg.av_sync, raw["av_sync"])
        if "pcr" in raw:
            cfg.pcr = _merge_section(PcrConfig, cfg.pcr, raw["pcr"])
        if "tools" in raw:
            cfg.tools = _merge_section(ToolsConfig, cfg.tools, raw["tools"])
    return cfg
