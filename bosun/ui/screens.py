"""Second-screen output: show the faceplate, spectrum or video full-screen on
another monitor (or a TV connected to the computer)."""

from __future__ import annotations

import contextlib
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

import numpy as np

from ..raster import png_bytes

CONTENT = ("Spectrum and waterfall", "Video (analogue TV / FPV)", "Faceplate")


@dataclass
class Monitor:
    x: int
    y: int
    width: int
    height: int
    name: str
    primary: bool = False

    def label(self) -> str:
        return (f"{self.name}: {self.width}x{self.height} at {self.x},{self.y}"
                + (" (main)" if self.primary else ""))


def monitors(root: tk.Misc) -> list[Monitor]:
    try:
        from screeninfo import get_monitors

        found = [Monitor(m.x, m.y, m.width, m.height, m.name or f"Screen {i + 1}",
                         bool(getattr(m, "is_primary", False)))
                 for i, m in enumerate(get_monitors())]
        if found:
            return sorted(found, key=lambda m: (not m.primary, m.x, m.y))
    except Exception:
        pass
    return [Monitor(0, 0, root.winfo_screenwidth(), root.winfo_screenheight(), "Screen 1",
                    True)]


def place_fullscreen(win: tk.Toplevel, mon: Monitor) -> None:
    """Move a window onto a monitor and make it full screen there."""
    win.attributes("-fullscreen", False)
    win.geometry(f"{mon.width}x{mon.height}+{mon.x}+{mon.y}")
    win.update_idletasks()

    def go():
        with contextlib.suppress(tk.TclError):
            win.attributes("-fullscreen", True)

    win.after(150, go)


class ScreenWindow(tk.Toplevel):
    """Full-screen picture of the spectrum or the video; Esc or double-click closes."""

    def __init__(self, app, content: str, mon: Monitor) -> None:
        super().__init__(app.root)
        self.app, self.content = app, content
        self.title(f"Bosun - {content}")
        self.configure(background="black")
        self.canvas = tk.Canvas(self, background="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._photo = None
        self._pending = None
        self.bind("<Escape>", lambda _e: self.close())
        self.canvas.bind("<Double-Button-1>", lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._hook(True)
        place_fullscreen(self, mon)
        self.after(60, self._tick)

    def _source_list(self):
        if self.content.startswith("Spectrum"):
            sp = self.app.spectrum
            if sp is None:
                return None
            if not hasattr(sp, "frame_listeners"):
                sp.frame_listeners = []
            return sp.frame_listeners
        vw = getattr(self.app, "video_window", None)
        return vw.listeners if vw is not None else None

    def _hook(self, on: bool) -> None:
        lst = self._source_list()
        if lst is None:
            return
        if on and self._receive not in lst:
            lst.append(self._receive)
        elif not on and self._receive in lst:
            lst.remove(self._receive)

    def _receive(self, frame) -> None:
        self._pending = frame  # drawn on the next tick (UI thread)

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        frame, self._pending = self._pending, None
        if frame is not None:
            if hasattr(frame, "convert"):
                frame = np.asarray(frame.convert("RGB"))
            if frame.ndim == 2:
                frame = np.repeat(frame[..., None], 3, axis=2)
            w, h = max(self.winfo_width(), 64), max(self.winfo_height(), 48)
            scale = min(w / frame.shape[1], h / frame.shape[0])
            ys = np.linspace(0, frame.shape[0] - 1, max(1, int(frame.shape[0] * scale))
                             ).astype(int)
            xs = np.linspace(0, frame.shape[1] - 1, max(1, int(frame.shape[1] * scale))
                             ).astype(int)
            self._photo = tk.PhotoImage(data=png_bytes(frame[ys][:, xs], level=0))
            self.canvas.delete("all")
            self.canvas.create_image(w // 2, h // 2, image=self._photo)
        elif self._source_list() is None:
            self.canvas.delete("all")
            self.canvas.create_text(self.winfo_width() // 2, self.winfo_height() // 2,
                                    fill="#d4af37", font=("Helvetica", 24),
                                    text=f"{self.content}: not running yet")
        self._hook(True)  # re-hook if the source window was reopened
        self.after(60, self._tick)

    def close(self) -> None:
        self._hook(False)
        self.destroy()


class SecondScreenDialog(tk.Toplevel):
    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Second screen")
        self.transient(app.root)
        self.resizable(False, False)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        ttk.Label(f, text="Show", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky="w")
        self.content = tk.StringVar(value=CONTENT[0])
        for i, c in enumerate(CONTENT):
            ttk.Radiobutton(f, text=c, value=c, variable=self.content).grid(
                row=i + 1, column=0, sticky="w")
        ttk.Label(f, text="On", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=1, sticky="w", padx=(20, 0))
        self.mons = monitors(app.root)
        self.mon = tk.StringVar(value=(self.mons[1] if len(self.mons) > 1 else
                                       self.mons[0]).label())
        for i, m in enumerate(self.mons):
            ttk.Radiobutton(f, text=m.label(), value=m.label(), variable=self.mon).grid(
                row=i + 1, column=1, sticky="w", padx=(20, 0))
        if len(self.mons) == 1:
            ttk.Label(f, foreground="#a60", wraplength=360, text=(
                "Only one screen found. Connect a second monitor or TV (extend the "
                "desktop, not mirror), then open this again.")).grid(
                row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(f, foreground="#555", text="Esc or double-click closes the full-screen "
                                             "view.").grid(row=10, column=0, columnspan=2,
                                                          sticky="w", pady=(8, 0))
        ttk.Button(f, text="Show", command=self.show).grid(row=11, column=1, sticky="e",
                                                           pady=(10, 0))

    def show(self) -> None:
        mon = next(m for m in self.mons if m.label() == self.mon.get())
        content = self.content.get()
        if content == "Faceplate":
            fp = self.app.open_faceplate()
            place_fullscreen(fp, mon)
        else:
            if content.startswith("Video") and getattr(self.app, "video_window", None) is None:
                self.app.open_video()
            self.app.screens.append(ScreenWindow(self.app, content, mon))
        self.destroy()
