# Packaging

## GUI 桌面程序

安装 GUI 依赖后可直接运行：

```powershell
cd D:\code\streamPts
pip install -e ".[gui]"
streampts-gui
```

或：

```powershell
set PYTHONPATH=src
python -m streampts.gui
```

功能：拖拽/选择片源、设置 ffprobe 与分析参数、后台分析、完成后自动打开 HTML 报告。

设置会保存到 `~/.streampts-gui.json`，仍可与 `~/.streampts.toml` 中的 ffprobe 默认路径配合使用。

## 打包 Windows exe

需要 Python 3.10+ 与 pip：

```powershell
packaging\build-gui.bat
```

输出：`dist\StreamPtsAnalyzer\` 文件夹（内含 `StreamPtsAnalyzer.exe`）。

采用 **onedir** 模式。必须拷贝**整个** `StreamPtsAnalyzer` 文件夹（含 `_internal`），**不要只拷 exe**，否则报错 `Cannot load PyInstaller's embedded PKG archive`。

拷贝后创建桌面快捷方式（带 logo）：运行 `CreateShortcut.bat`。

图标不要用 rcedit 二次写入（会破坏 PyInstaller 启动包）。

手动打包：

```powershell
pip install -e ".[gui,build]"
pyinstaller packaging\streampts-gui.spec --noconfirm --clean
```

## CLI

MVP 仍支持 `pip install -e .` 后使用 `streampts analyze input.ts`。
