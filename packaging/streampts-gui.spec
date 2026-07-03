# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — onedir build for fast GUI startup."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

project_root = Path(SPECPATH).resolve().parent
assets_dir = project_root / "src" / "streampts" / "gui" / "assets"
icon_file = assets_dir / "logo.ico"

if not icon_file.is_file():
    raise SystemExit(f"Icon not found: {icon_file}. Run packaging/generate-icon.py first.")
print(f"Using application icon: {icon_file}")

# plotly HTML 使用 CDN，无需打包 plotly 的 JS 资源；分析时再 lazy-import Python 模块。
hiddenimports = [
    "streampts",
    "streampts.analyze_service",
    "streampts.gui.app",
    "streampts.gui.launcher",
    "streampts.report.plotly_builder",
    "plotly.graph_objects",
    "plotly.subplots",
    "plotly.io",
    "plotly.io._html",
    "tkinterdnd2",
    "tomli",
    "numpy",
]

excludes = [
    "matplotlib",
    "pytest",
    "plotly.matplotlylib",
    "IPython",
    "notebook",
    "pandas",
    "scipy",
]

datas = (
    collect_data_files("customtkinter")
    + collect_data_files("tkinterdnd2")
    + [(str(assets_dir), "streampts/gui/assets")]
)

a = Analysis(
    [str(project_root / "src" / "streampts" / "gui" / "launcher.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StreamPtsAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StreamPtsAnalyzer",
)
