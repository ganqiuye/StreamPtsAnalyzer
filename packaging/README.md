# Packaging

## GUI 桌面程序

```powershell
pip install -e ".[gui]"
streampts-gui
```

或：

```powershell
python streampts-gui.py
```

功能：拖拽/选择片源、设置 ffprobe 与分析参数、后台分析、完成后打开 HTML 报告。

GUI 设置保存在 `~/.streampts-gui.json`；`~/.streampts.toml` 可配置默认 ffprobe 路径。

## 打包 Windows exe

需要 Python 3.10+：

```powershell
packaging\build-gui.bat
```

输出：`dist\StreamPtsAnalyzer\` 文件夹（内含 `StreamPtsAnalyzer.exe`）。

采用 **onedir** 模式。分发时必须拷贝**整个** `StreamPtsAnalyzer` 文件夹（含 `_internal`），**不要只拷 exe**，否则会报错 `Cannot load PyInstaller's embedded PKG archive`。

拷贝后创建带图标的桌面快捷方式：运行目录内的 `CreateShortcut.bat`。

手动打包：

```powershell
pip install -e ".[gui,build]"
pyinstaller packaging\streampts-gui.spec --noconfirm --clean
```

## CLI

```powershell
pip install -e .
streampts analyze input.ts --open
```
