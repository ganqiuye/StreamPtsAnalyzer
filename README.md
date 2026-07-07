# Stream PTS Analyzer

基于本地 `ffprobe` 分析媒体文件中的 PTS（Presentation Time Stamp），生成交互式 HTML 报告。

支持 MPEG-TS、AVI、MKV、MP4 等常见封装；PCR 分析仅适用于 MPEG-TS。

<img width="2540" height="1223" alt="QQ_1783057930465" src="https://github.com/user-attachments/assets/7c7e94a2-7ab2-404e-94ba-4d82c992a2ca" />


## 系统要求

- Windows 10/11（GUI / 打包 exe）
- Python 3.10+
- [ffmpeg](https://ffmpeg.org/)（需包含 `ffprobe`，并加入 PATH，或在界面/配置中指定路径）

## 快速开始

### GUI 桌面程序（推荐）

```powershell
cd <解压目录>
pip install -e ".[gui]"
streampts-gui
```

或直接运行（无需 pip 安装）：

```powershell
python streampts-gui.py
```

拖拽或选择片源 → 设置参数 → 开始分析 → 自动打开 HTML 报告。

### 命令行

```powershell
pip install -e .
streampts analyze your_file.ts --open
```

或：

```powershell
python streampts.py analyze your_file.avi --open
```

报告默认保存在片源同目录：`{片源名}.pts-report.html`。

## 支持的片源格式

| 格式 | 说明 |
|------|------|
| `.ts` `.mts` `.trp` `.m2ts` | MPEG-TS，支持 PCR / Program |
| `.avi` `.mkv` `.mp4` `.mov` 等 | 通用容器；视频流若无 PTS 会自动回退使用 DTS |
| 其他 ffprobe 可读格式 | 一般可分析音视频 PTS，PCR 通常不可用 |

## ffprobe 路径

若未加入 PATH，可任选其一：

```powershell
streampts analyze input.ts --ffprobe-path D:/tools/ffmpeg/bin/ffprobe.exe
```

或在用户目录创建 `~/.streampts.toml`：

```toml
[tools]
ffprobe_path = "D:/tools/ffmpeg/bin/ffprobe.exe"
```

GUI 中也可在「ffprobe」栏直接填写路径。

## 常用命令

```powershell
streampts analyze input.ts
streampts analyze input.ts --open
streampts analyze input.ts -o report.html --program 0 --unit us
streampts analyze large.ts --range 00:10:00-00:20:00
streampts analyze input.ts --jump-min-ms 40 --jump-factor 10 --annotate-top 20
```

## 配置（可选）

`~/.streampts.toml` 或项目目录下的 `.streampts.toml`：

```toml
[jump]
min_ms = 40
factor = 10
max_ms = 5000
annotate_top = 20

[av_sync]
threshold_ms = 40

[pcr]
interval_min_ms = 10
interval_max_ms = 100

[tools]
ffprobe_path = ""
```

## 报告功能

- 同图 / 分开布局，按 Program / Stream 筛选（Stream 可多选）
- Video / Audio / PCR PTS 曲线（PCR 仅 TS）
- 跳变、回退、不连续标记
- A-V 同步偏差、PCR 间隔子图
- 滚轮缩放、鼠标平移

## 打包 Windows exe

若需分发给没有 Python 的用户，可自行打包：

```powershell
packaging\build-gui.bat
```

输出目录：`dist\StreamPtsAnalyzer\`（**必须拷贝整个文件夹**，含 `_internal`）。

详细说明见 `packaging/README.md`。

## 目录结构

```
StreamPtsAnalyzer/
  src/streampts/     # 程序源码
  packaging/         # Windows exe 打包脚本
  streampts.py       # CLI 启动脚本
  streampts-gui.py   # GUI 启动脚本
  pyproject.toml
```

## 许可

随源码一并发布；使用 ffprobe 须遵守 [FFmpeg 许可](https://ffmpeg.org/legal.html)。
