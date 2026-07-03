"""Minimal entry point: show splash immediately, then load the full GUI."""

from __future__ import annotations

import sys
import tkinter as tk

from streampts.gui.branding import asset_path, has_logo
from streampts.gui.win_shell import register_application_icon


def _apply_window_icon(window: tk.Tk | tk.Toplevel) -> None:
    if sys.platform != "win32":
        return
    ico_path = asset_path("logo.ico")
    if not ico_path.is_file():
        return
    try:
        window.iconbitmap(default=str(ico_path))
    except tk.TclError:
        pass


def _show_splash() -> tk.Tk:
    splash = tk.Tk()
    splash.title("Stream PTS Analyzer")
    splash.resizable(False, False)
    splash.configure(bg="#1a1a1a")
    _apply_window_icon(splash)

    width, height = 400, 120
    x = max(0, (splash.winfo_screenwidth() - width) // 2)
    y = max(0, (splash.winfo_screenheight() - height) // 2)
    splash.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(splash, bg="#1a1a1a")
    frame.pack(fill="both", expand=True, padx=24, pady=20)

    text_frame = tk.Frame(frame, bg="#1a1a1a")
    text_frame.pack(side="left", fill="both", expand=True)

    if has_logo():
        try:
            from PIL import Image, ImageTk

            logo = Image.open(asset_path("logo.png")).resize((44, 44), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(logo)
            logo_label = tk.Label(frame, image=photo, bg="#1a1a1a")
            logo_label.image = photo  # type: ignore[attr-defined]
            logo_label.pack(side="left", padx=(0, 14))
        except OSError:
            pass

    tk.Label(
        text_frame,
        text="Stream PTS Analyzer",
        fg="#e8e8e8",
        bg="#1a1a1a",
        font=("Segoe UI", 15, "bold"),
    ).pack(anchor="w")
    tk.Label(
        text_frame,
        text="正在启动…",
        fg="#888888",
        bg="#1a1a1a",
        font=("Segoe UI", 10),
    ).pack(anchor="w", pady=(8, 0))

    splash.update_idletasks()
    splash.update()
    return splash


def main() -> None:
    register_application_icon()
    splash = _show_splash()
    try:
        from streampts.gui.app import main as app_main
    finally:
        splash.destroy()
    app_main()


if __name__ == "__main__":
    main()
