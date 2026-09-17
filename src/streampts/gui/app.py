from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinterdnd2 import DND_FILES, TkinterDnD

from streampts import __author__, __version__
from streampts.analyze_service import AnalyzeError, AnalyzeOptions, apply_options_to_config, default_output, open_report_path
from streampts.config import load_config
from streampts.extractor.ffprobe import FfprobeError, resolve_ffprobe
from streampts.gui.branding import asset_path, has_logo

SETTINGS_PATH = Path.home() / ".streampts-gui.json"


def _load_gui_settings() -> dict:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_gui_settings(data: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _preload_heavy_modules() -> None:
    try:
        import numpy  # noqa: F401
        import plotly.graph_objects  # noqa: F401
    except ImportError:
        pass


class StreamPtsApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"Stream PTS Analyzer v{__version__} by {__author__}")
        self.geometry("720x680")
        self.minsize(640, 600)

        self._input_path: Path | None = None
        self._output_path: Path | None = None
        self._busy = False
        self._analyze_stage = "就绪"
        self._analyze_started_at = 0.0
        self._timer_job: str | None = None
        self._logo_ctk = None

        cfg = load_config()
        saved = _load_gui_settings()

        self._dnd_ready = False
        self._init_logo()
        self._apply_window_icon()
        self._build_ui(cfg, saved)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(0, self._init_dnd)
        self.after(0, self._fill_ffprobe_default)
        self.update_idletasks()
        self.update()

    def _init_logo(self) -> None:
        if not has_logo():
            return
        try:
            from PIL import Image

            logo_path = asset_path("logo.png")
            logo_image = Image.open(logo_path)
            self._logo_ctk = ctk.CTkImage(
                light_image=logo_image,
                dark_image=logo_image,
                size=(52, 52),
            )
        except OSError:
            self._logo_ctk = None

    def _apply_window_icon(self) -> None:
        if sys.platform != "win32":
            return
        ico_path = asset_path("logo.ico")
        if not ico_path.is_file():
            return
        try:
            self.iconbitmap(default=str(ico_path))
        except tk.TclError:
            pass

    def _build_ui(self, cfg, saved: dict) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        header.grid_columnconfigure(1, weight=1)

        title_col = 0
        if self._logo_ctk is not None:
            ctk.CTkLabel(header, image=self._logo_ctk, text="").grid(
                row=0, column=0, rowspan=2, padx=(0, 14), sticky="nw"
            )
            title_col = 1

        ctk.CTkLabel(
            header,
            text="Stream PTS Analyzer",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=title_col, sticky="w")
        ctk.CTkLabel(
            header,
            text="拖拽媒体片源，生成交互式 PTS 报告",
            font=ctk.CTkFont(size=13),
            text_color=("gray40", "gray65"),
        ).grid(row=1, column=title_col, sticky="w", pady=(4, 0))

        self._drop_host = tk.Frame(
            self,
            bg="#1c1c1c",
            highlightthickness=2,
            highlightbackground="#4a4a4a",
            height=120,
        )
        self._drop_host.grid(row=1, column=0, sticky="ew", padx=24, pady=8)
        self._drop_host.grid_propagate(False)
        self._drop_host.grid_columnconfigure(0, weight=1)

        drop_text = "将 .ts / .avi / .mkv / .mp4 等文件拖放到此处\n或点击选择片源"
        self._drop_label_tk = tk.Label(
            self._drop_host,
            text=drop_text,
            bg="#1c1c1c",
            fg="#9a9a9a",
            font=("Segoe UI", 14),
            justify="center",
            cursor="hand2",
        )
        self._drop_label_tk.grid(row=0, column=0, pady=28)
        self._drop_host.bind("<Button-1>", lambda _e: self._browse_input())
        self._drop_label_tk.bind("<Button-1>", lambda _e: self._browse_input())

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        body.grid_columnconfigure(1, weight=1)

        row = 0
        ctk.CTkLabel(body, text="片源", anchor="w").grid(row=row, column=0, sticky="w", pady=6)
        self._input_var = tk.StringVar(value="")
        input_row = ctk.CTkFrame(body, fg_color="transparent")
        input_row.grid(row=row, column=1, sticky="ew", pady=6)
        input_row.grid_columnconfigure(0, weight=1)
        self._input_entry = ctk.CTkEntry(input_row, textvariable=self._input_var)
        self._input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(input_row, text="浏览", width=72, command=self._browse_input).grid(row=0, column=1)

        row += 1
        ctk.CTkLabel(body, text="输出 HTML", anchor="w").grid(row=row, column=0, sticky="w", pady=6)
        self._output_var = tk.StringVar(value="")
        output_row = ctk.CTkFrame(body, fg_color="transparent")
        output_row.grid(row=row, column=1, sticky="ew", pady=6)
        output_row.grid_columnconfigure(0, weight=1)
        self._output_entry = ctk.CTkEntry(
            output_row,
            textvariable=self._output_var,
            placeholder_text="留空则与片源同目录",
        )
        self._output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(output_row, text="浏览", width=72, command=self._browse_output).grid(row=0, column=1)

        row += 1
        ctk.CTkLabel(body, text="ffprobe", anchor="w").grid(row=row, column=0, sticky="w", pady=6)
        ffprobe_row = ctk.CTkFrame(body, fg_color="transparent")
        ffprobe_row.grid(row=row, column=1, sticky="ew", pady=6)
        ffprobe_row.grid_columnconfigure(0, weight=1)
        default_ffprobe = saved.get("ffprobe_path") or cfg.tools.ffprobe_path or ""
        self._ffprobe_var = tk.StringVar(value=default_ffprobe)
        self._ffprobe_entry = ctk.CTkEntry(
            ffprobe_row,
            textvariable=self._ffprobe_var,
            placeholder_text="留空则自动搜索 PATH / 常见安装目录",
        )
        self._ffprobe_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(ffprobe_row, text="浏览", width=72, command=self._browse_ffprobe).grid(row=0, column=1)

        row += 1
        opts = ctk.CTkFrame(body, fg_color="transparent")
        opts.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        for col in range(4):
            opts.grid_columnconfigure(col, weight=1)

        ctk.CTkLabel(opts, text="默认节目").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._program_var = tk.StringVar(value=str(saved.get("program", 0)))
        ctk.CTkEntry(opts, textvariable=self._program_var, width=80).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(opts, text="PTS 单位").grid(row=0, column=2, sticky="w", padx=(16, 8))
        self._unit_var = tk.StringVar(value=saved.get("unit", cfg.default_unit))
        ctk.CTkOptionMenu(opts, variable=self._unit_var, values=["us", "90k", "ms", "sec"], width=100).grid(
            row=0, column=3, sticky="w"
        )

        row += 1
        ctk.CTkLabel(body, text="时间范围", anchor="w").grid(row=row, column=0, sticky="w", pady=6)
        self._range_var = tk.StringVar(value=saved.get("time_range", ""))
        ctk.CTkEntry(
            body,
            textvariable=self._range_var,
            placeholder_text="可选，如 00:10:00-00:20:00",
        ).grid(row=row, column=1, sticky="ew", pady=6)

        row += 1
        flags = ctk.CTkFrame(body, fg_color="transparent")
        flags.grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        self._full_var = tk.BooleanVar(value=saved.get("force_full", False))
        self._open_var = tk.BooleanVar(value=saved.get("open_report", True))
        ctk.CTkCheckBox(flags, text="强制全量解析", variable=self._full_var).grid(row=0, column=0, padx=(0, 16))
        ctk.CTkCheckBox(flags, text="完成后打开 HTML", variable=self._open_var).grid(row=0, column=1)

        row += 1
        self._advanced_visible = tk.BooleanVar(value=False)
        ctk.CTkButton(
            body,
            text="高级参数 ▾",
            width=120,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            command=self._toggle_advanced,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))

        row += 1
        self._advanced_frame = ctk.CTkFrame(body, fg_color=("gray90", "gray20"))
        self._advanced_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._advanced_frame.grid_columnconfigure(1, weight=1)
        self._advanced_frame.grid_columnconfigure(3, weight=1)
        self._advanced_frame.grid_remove()

        adv = self._advanced_frame
        self._jump_min_var = tk.StringVar(value=str(saved.get("jump_min_ms", cfg.jump.min_ms)))
        self._jump_factor_var = tk.StringVar(value=str(saved.get("jump_factor", cfg.jump.factor)))
        self._jump_max_var = tk.StringVar(value=str(saved.get("jump_max_ms", cfg.jump.max_ms or "")))
        self._annotate_var = tk.StringVar(value=str(saved.get("annotate_top", cfg.jump.annotate_top)))
        self._av_var = tk.StringVar(value=str(saved.get("av_threshold_ms", cfg.av_sync.threshold_ms)))
        self._threshold_var = tk.StringVar(value=str(saved.get("threshold_mb", cfg.threshold_mb)))
        self._timeout_var = tk.StringVar(value=str(saved.get("timeout", cfg.timeout)))

        adv_fields = [
            ("Jump 最小 (ms)", self._jump_min_var, 0, 0),
            ("Jump 因子", self._jump_factor_var, 0, 2),
            ("Jump 最大 (ms)", self._jump_max_var, 1, 0),
            ("标注 Top N", self._annotate_var, 1, 2),
            ("A/V 阈值 (ms)", self._av_var, 2, 0),
            ("降采样阈值 (MB)", self._threshold_var, 2, 2),
            ("ffprobe 超时 (s)", self._timeout_var, 3, 0),
        ]
        for label, var, r, c in adv_fields:
            ctk.CTkLabel(adv, text=label, anchor="w").grid(row=r, column=c, sticky="w", padx=12, pady=8)
            ctk.CTkEntry(adv, textvariable=var, width=120).grid(row=r, column=c + 1, sticky="w", padx=(0, 12), pady=8)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=24, pady=(8, 20))
        footer.grid_columnconfigure(0, weight=1)

        self._progress = ctk.CTkProgressBar(footer, mode="indeterminate")
        self._progress.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._progress.grid_remove()

        self._status_var = tk.StringVar(value="就绪")
        ctk.CTkLabel(footer, textvariable=self._status_var, anchor="w", text_color=("gray35", "gray65")).grid(
            row=1, column=0, sticky="ew"
        )

        btn_row = ctk.CTkFrame(footer, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="e", pady=(12, 0))
        self._open_btn = ctk.CTkButton(btn_row, text="打开报告", width=100, command=self._open_last_report, state="disabled")
        self._open_btn.grid(row=0, column=0, padx=(0, 8))
        self._analyze_btn = ctk.CTkButton(btn_row, text="开始分析", width=120, command=self._start_analyze)
        self._analyze_btn.grid(row=0, column=1)

    def _init_dnd(self) -> None:
        try:
            TkinterDnD._require(self)
            self._dnd_ready = True
            self._register_drop_target(self._drop_host)
            self._register_drop_target(self._drop_label_tk)
        except RuntimeError:
            self._dnd_ready = False
            self._drop_label_tk.configure(
                text=self._drop_label_tk.cget("text") + "\n(拖拽不可用，请使用浏览按钮)",
            )

    def _fill_ffprobe_default(self) -> None:
        if self._ffprobe_var.get().strip():
            return
        try:
            self._ffprobe_var.set(resolve_ffprobe(load_config()))
        except FfprobeError:
            pass

    def _register_drop_target(self, widget: tk.Widget) -> None:
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self._on_dnd_drop)
        widget.dnd_bind("<<DragEnter>>", self._on_dnd_enter)
        widget.dnd_bind("<<DragLeave>>", self._on_dnd_leave)

    def _on_dnd_enter(self, _event) -> None:
        self._drop_host.configure(highlightbackground="#1f6aa5")

    def _on_dnd_leave(self, _event) -> None:
        self._drop_host.configure(highlightbackground="#4a4a4a")

    def _on_dnd_drop(self, event) -> None:
        if self._busy:
            return
        for raw in self.tk.splitlist(event.data):
            path = Path(str(raw).strip().strip("{}"))
            if path.is_file():
                self._set_input_path(path)
                break
        self._drop_host.configure(highlightbackground="#4a4a4a")

    def _set_input_path(self, path: Path) -> None:
        self._input_path = path.resolve()
        self._input_var.set(str(self._input_path))
        suggested = default_output(self._input_path)
        self._output_path = suggested
        self._output_var.set(str(suggested))
        self._drop_label_tk.configure(
            text=f"已选择\n{self._input_path.name}",
            fg="#e0e0e0",
            font=("Segoe UI", 15, "bold"),
        )

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择片源",
            filetypes=[
                ("媒体文件", "*.ts *.mts *.trp *.m2ts *.avi *.mkv *.mp4 *.mov *.flv *.wmv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._set_input_path(Path(path))

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存 HTML 报告",
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")],
        )
        if path:
            self._output_path = Path(path)
            self._output_var.set(str(self._output_path))

    def _browse_ffprobe(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 ffprobe",
            filetypes=[("ffprobe", "ffprobe.exe"), ("All files", "*.*")],
        )
        if path:
            self._ffprobe_var.set(path)

    def _toggle_advanced(self) -> None:
        if self._advanced_frame.winfo_ismapped():
            self._advanced_frame.grid_remove()
            self._advanced_visible.set(False)
        else:
            self._advanced_frame.grid()
            self._advanced_visible.set(True)

    def _parse_optional_float(self, value: str) -> float | None:
        value = value.strip()
        if not value:
            return None
        return float(value)

    def _parse_optional_int(self, value: str) -> int | None:
        value = value.strip()
        if not value:
            return None
        return int(value)

    def _collect_options(self) -> AnalyzeOptions:
        input_text = self._input_var.get().strip()
        if not input_text:
            raise ValueError("请先选择片源文件")
        input_path = Path(input_text)

        output_text = self._output_var.get().strip()
        output_path = Path(output_text) if output_text else None

        ffprobe_text = self._ffprobe_var.get().strip()
        range_text = self._range_var.get().strip()

        return AnalyzeOptions(
            input=input_path,
            output=output_path,
            program=int(self._program_var.get().strip() or "0"),
            time_range=range_text or None,
            force_full=self._full_var.get(),
            unit=self._unit_var.get(),  # type: ignore[arg-type]
            open_report=False,
            ffprobe_path=ffprobe_text or None,
            jump_min_ms=self._parse_optional_float(self._jump_min_var.get()),
            jump_factor=self._parse_optional_float(self._jump_factor_var.get()),
            jump_max_ms=self._parse_optional_float(self._jump_max_var.get()),
            annotate_top=self._parse_optional_int(self._annotate_var.get()),
            av_threshold_ms=self._parse_optional_float(self._av_var.get()),
            threshold_mb=self._parse_optional_float(self._threshold_var.get()),
            timeout=self._parse_optional_int(self._timeout_var.get()),
        )

    def _persist_settings(self) -> None:
        _save_gui_settings(
            {
                "ffprobe_path": self._ffprobe_var.get().strip(),
                "program": int(self._program_var.get().strip() or "0"),
                "unit": self._unit_var.get(),
                "time_range": self._range_var.get().strip(),
                "force_full": self._full_var.get(),
                "open_report": self._open_var.get(),
                "jump_min_ms": self._jump_min_var.get().strip(),
                "jump_factor": self._jump_factor_var.get().strip(),
                "jump_max_ms": self._jump_max_var.get().strip(),
                "annotate_top": self._annotate_var.get().strip(),
                "av_threshold_ms": self._av_var.get().strip(),
                "threshold_mb": self._threshold_var.get().strip(),
                "timeout": self._timeout_var.get().strip(),
            }
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._analyze_btn.configure(state=state)
        if busy:
            self._progress.grid()
            self._progress.start()
        else:
            self._progress.stop()
            self._progress.grid_remove()
            if self._timer_job is not None:
                self.after_cancel(self._timer_job)
                self._timer_job = None

    def _update_progress(self, message: str) -> None:
        self._analyze_stage = message
        elapsed = int(time.time() - self._analyze_started_at)
        self._status_var.set(f"{message}（{elapsed}s）")

    def _tick_progress_timer(self) -> None:
        if not self._busy:
            return
        elapsed = int(time.time() - self._analyze_started_at)
        self._status_var.set(f"{self._analyze_stage}（{elapsed}s）")
        self._timer_job = self.after(500, self._tick_progress_timer)

    def _start_analyze(self) -> None:
        if self._busy:
            return
        try:
            options = self._collect_options()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        except (TypeError, ValueError) as exc:
            messagebox.showerror("参数错误", f"请检查数值参数: {exc}")
            return

        if not options.input.is_file():
            messagebox.showerror("参数错误", f"片源文件不存在:\n{options.input}")
            return

        cfg = apply_options_to_config(load_config(options.input.parent), options)
        try:
            ffprobe_path = resolve_ffprobe(cfg)
        except FfprobeError as exc:
            messagebox.showerror("ffprobe 未找到", str(exc))
            return

        if not self._ffprobe_var.get().strip():
            self._ffprobe_var.set(ffprobe_path)

        self._persist_settings()
        self._set_busy(True)
        self._analyze_started_at = time.time()
        self._analyze_stage = "准备分析…"
        self._update_progress(self._analyze_stage)
        self._tick_progress_timer()
        self._open_btn.configure(state="disabled")
        open_after = self._open_var.get()

        def worker() -> None:
            try:
                def progress(msg: str) -> None:
                    self.after(0, lambda m=msg: self._update_progress(m))

                from streampts.analyze_service import run_analyze

                output = run_analyze(options, progress=progress)
                self.after(0, lambda out=output: self._on_success(out, open_after))
            except AnalyzeError as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._on_error(m))
            except Exception as exc:  # noqa: BLE001
                msg = str(exc) or exc.__class__.__name__
                self.after(0, lambda m=msg: self._on_error(m))

        threading.Thread(target=worker, daemon=True, name="streampts-analyze").start()

    def _on_success(self, output: Path, open_after: bool) -> None:
        self._output_path = output
        self._output_var.set(str(output))
        self._set_busy(False)
        self._status_var.set(f"完成 — {output.name}")
        self._open_btn.configure(state="normal")
        if open_after:
            try:
                open_report_path(output)
            except OSError as exc:
                messagebox.showerror("打开报告失败", str(exc))

    def _on_error(self, message: str) -> None:
        self._set_busy(False)
        self._status_var.set("分析失败")
        messagebox.showerror("分析失败", message)

    def _open_last_report(self) -> None:
        if self._output_path and self._output_path.is_file():
            open_report_path(self._output_path)
            return
        output_text = self._output_var.get().strip()
        if output_text and Path(output_text).is_file():
            open_report_path(Path(output_text))
            return
        messagebox.showinfo("提示", "还没有可打开的报告")

    def _on_close(self) -> None:
        self._persist_settings()
        self.destroy()


def main() -> None:
    app = StreamPtsApp()
    threading.Thread(target=_preload_heavy_modules, daemon=True, name="streampts-preload").start()
    app.mainloop()


if __name__ == "__main__":
    main()
