"""Analogue video viewer: FPV (FM) and broadcast (AM) PAL/NTSC, black and white."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

from .. import atv
from ..raster import png_bytes
from ..recorder import recordings_dir, stamp
from ..sources import RTL_TCP_DEFAULT, list_sources, open_source
from .tips import tip

PAD = 6
TEST = atv.ATVTestSource.name
RATES = {"8 MS/s (broadcast TV)": 8e6, "10 MS/s": 10e6, "16 MS/s (FPV)": 16e6,
         "20 MS/s (FPV, HackRF max)": 20e6, "2.4 MS/s (RTL-SDR, blurry)": 2.4e6}
TIPS = {
    "v_source": "Analogue video needs a wide receiver: HackRF One (up to 20 MS/s). An RTL-SDR "
                "(2.4 MS/s) shows only a blurry picture. 'Test pattern' simulates a "
                "transmitter so you can try the viewer.",
    "v_freq": "Video carrier frequency in MHz, or pick an FPV channel.",
    "v_std": "PAL (625 lines, most of the world) or NTSC (525 lines, the Americas, Japan, "
             "South Korea). Most FPV cameras can be set to either.",
    "v_mod": "FM for drone FPV and amateur TV; AM for broadcast analogue TV.",
    "v_invert": "Tick if the picture looks like a photo negative (some transmitters invert).",
}


class VideoWindow(tk.Toplevel):
    def __init__(self, app) -> None:
        super().__init__(app.root)
        self.app = app
        self.title("Bosun video")
        self.geometry("820x700")
        self.source = None
        self.decoder: atv.ATVDecoder | None = None
        self.frames: queue.Queue = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread = None
        self._photo = None
        self.last_frame: np.ndarray | None = None
        self.video_rec = None
        self.listeners: list = []  # e.g. a second-screen window
        self.fps = 0.0
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self._tick)

    def _build(self) -> None:
        bar = ttk.Frame(self, padding=PAD)
        bar.pack(fill="x")
        ttk.Label(bar, text="Source").grid(row=0, column=0, sticky="w")
        self.src = tk.StringVar(value=TEST)
        self.src_box = ttk.Combobox(bar, textvariable=self.src, width=30,
                                    values=[TEST, RTL_TCP_DEFAULT])
        self.src_box.grid(row=0, column=1, sticky="w", padx=PAD)
        self._tip(self.src_box, "v_source")
        ttk.Button(bar, text="Find SDRs", command=self._find).grid(row=0, column=2)
        ttk.Label(bar, text="Frequency MHz").grid(row=0, column=3, padx=(PAD * 2, 0))
        self.freq = tk.StringVar(value="5806")
        e = ttk.Entry(bar, textvariable=self.freq, width=10)
        e.grid(row=0, column=4, padx=PAD)
        e.bind("<Return>", lambda _e: self.retune())
        self._tip(e, "v_freq")
        self.chan = tk.StringVar(value="5.8G Raceband R5")
        cb = ttk.Combobox(bar, textvariable=self.chan, values=list(atv.FPV_CHANNELS),
                          state="readonly", width=18)
        cb.grid(row=0, column=5)
        cb.bind("<<ComboboxSelected>>", self._pick_channel)
        self._tip(cb, "v_freq")

        ttk.Label(bar, text="Standard").grid(row=1, column=0, sticky="w", pady=PAD)
        self.std = tk.StringVar(value="PAL")
        s = ttk.Combobox(bar, textvariable=self.std, values=["PAL", "NTSC"], width=8,
                         state="readonly")
        s.grid(row=1, column=1, sticky="w", padx=PAD)
        self._tip(s, "v_std")
        ttk.Label(bar, text="Modulation").grid(row=1, column=2)
        self.mod = tk.StringVar(value="FM")
        m = ttk.Combobox(bar, textvariable=self.mod, values=["FM", "AM"], width=6,
                         state="readonly")
        m.grid(row=1, column=3, sticky="w", padx=PAD)
        self._tip(m, "v_mod")
        ttk.Label(bar, text="Rate").grid(row=1, column=4)
        self.rate = tk.StringVar(value="8 MS/s (broadcast TV)")
        ttk.Combobox(bar, textvariable=self.rate, values=list(RATES), width=24,
                     state="readonly").grid(row=1, column=5, sticky="w")
        self.invert = tk.BooleanVar(value=False)
        inv = ttk.Checkbutton(bar, text="Invert", variable=self.invert,
                              command=self._apply_invert)
        inv.grid(row=1, column=6, padx=PAD)
        self._tip(inv, "v_invert")

        btns = ttk.Frame(self, padding=(PAD, 0))
        btns.pack(fill="x")
        self.run_btn = ttk.Button(btns, text="Start", command=self.toggle)
        self.run_btn.pack(side="left")
        ttk.Button(btns, text="Snapshot PNG", command=self.snapshot).pack(side="left", padx=PAD)
        self.rec_btn = ttk.Button(btns, text="Record video", command=self.toggle_rec)
        self.rec_btn.pack(side="left")
        ttk.Label(btns, text="Gain").pack(side="left", padx=(PAD * 2, 2))
        self.gain = tk.DoubleVar(value=30)
        ttk.Scale(btns, from_=0, to=60, variable=self.gain, length=120).pack(side="left")
        self.status = tk.StringVar(value="Pick a source and press Start.")
        ttk.Label(self, textvariable=self.status, padding=PAD).pack(fill="x")
        self.canvas = tk.Canvas(self, background="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

    def _tip(self, widget, key) -> None:
        tip(widget, TIPS.get(key, key))

    def _find(self) -> None:
        self.status.set("Looking for SDRs...")

        def work():
            names = [TEST] + list_sources()[1:]
            self.app.post(self.src_box.configure, values=names)
            self.app.post(self.status.set, f"Sources: {', '.join(names)}")

        threading.Thread(target=work, daemon=True).start()

    def _pick_channel(self, _e=None) -> None:
        self.freq.set(str(atv.FPV_CHANNELS[self.chan.get()]))
        self.mod.set("FM")
        self.retune()

    def _apply_invert(self) -> None:
        if self.decoder is not None:
            self.decoder.invert = bool(self.invert.get())

    # ------------------------------------------------------------ run
    def toggle(self) -> None:
        if self._thread is not None:
            self.stop()
            return
        try:
            hz = float(self.freq.get()) * 1e6
            rate = RATES[self.rate.get()]
            std = atv.STANDARDS[self.std.get()]
            if self.src.get() == TEST:
                self.source = atv.ATVTestSource(rate, std, self.mod.get())
            else:
                self.source = open_source(self.src.get(), hz, rate, self.gain.get())
                if getattr(self.source, "max_rate", rate) < rate:
                    rate = self.source.max_rate
                    self.status.set(f"This SDR tops out at {rate / 1e6:g} MS/s: the picture "
                                    "will be blurry.")
                    if hasattr(self.source, "set_rate"):
                        self.source.set_rate(rate)
            self.decoder = atv.ATVDecoder(self.source.rate, std, self.mod.get(),
                                          invert=bool(self.invert.get()))
        except Exception as exc:
            self.status.set(f"Could not start: {exc}")
            self.source = None
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="video")
        self._thread.start()
        self.run_btn.configure(text="Stop")

    def _run(self) -> None:
        src, dec = self.source, self.decoder
        block = int(src.rate / 25)
        count, t0 = 0, time.monotonic()
        while not self._stop.is_set():
            try:
                if hasattr(src, "read_all"):
                    iq = src.read_all(block)
                    if len(iq) > block * 6:  # fell behind: skip ahead
                        iq = iq[-block * 2:]
                else:
                    iq = src.read(block)
            except Exception as exc:
                self.app.post(self.status.set, f"Video source error: {exc}")
                break
            for field in dec.process(iq):
                count += 1
                with contextlib.suppress(queue.Full):
                    self.frames.put_nowait(field)
            now = time.monotonic()
            if now - t0 > 1:
                self.fps, count, t0 = count / (now - t0), 0, now
            if isinstance(src, atv.ATVTestSource):
                time.sleep(block / src.rate * 0.9)  # real-time pace for the simulator

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        self._thread = None
        if self.source is not None:
            with contextlib.suppress(Exception):
                self.source.close()
        self.source = None
        if self.video_rec is not None:
            self.toggle_rec()
        self.run_btn.configure(text="Start")
        self.status.set("Stopped.")

    def retune(self) -> None:
        if self.source is not None:
            try:
                self.source.tune(float(self.freq.get()) * 1e6)
            except Exception as exc:
                self.status.set(f"Retune failed: {exc}")

    # ------------------------------------------------------------ display
    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        frame = None
        with contextlib.suppress(queue.Empty):
            while True:
                frame = self.frames.get_nowait()
        if frame is not None:
            self.last_frame = frame
            rgb = np.repeat(frame[..., None], 3, axis=2)
            w, h = max(self.canvas.winfo_width(), 64), max(self.canvas.winfo_height(), 48)
            scale = min(w / rgb.shape[1], h / rgb.shape[0])
            if abs(scale - 1) > 0.05:
                ys = np.linspace(0, rgb.shape[0] - 1, int(rgb.shape[0] * scale)).astype(int)
                xs = np.linspace(0, rgb.shape[1] - 1, int(rgb.shape[1] * scale)).astype(int)
                rgb = rgb[ys][:, xs]
            self._photo = tk.PhotoImage(data=png_bytes(rgb))
            self.canvas.delete("all")
            self.canvas.create_image(w // 2, h // 2, image=self._photo)
            if self.video_rec is not None:
                with contextlib.suppress(Exception):
                    self.video_rec.add(frame)
            for cb in list(self.listeners):
                with contextlib.suppress(Exception):
                    cb(frame)
            dec = self.decoder
            if dec is not None:
                lock = "locked" if dec.lock > 0.8 else "searching (try Invert, or check "\
                    "the frequency and standard)"
                self.status.set(f"{self.fps:.0f} fields/s, sync {lock}")
        self.after(40, self._tick)

    def snapshot(self) -> None:
        if self.last_frame is None:
            self.status.set("No picture yet.")
            return
        path = recordings_dir() / (stamp("video_snapshot") + ".png")
        path.write_bytes(png_bytes(np.repeat(self.last_frame[..., None], 3, axis=2)))
        self.app.say(f"Snapshot saved: {path}")
        self.status.set(f"Snapshot saved: {path.name}")

    def toggle_rec(self) -> None:
        from ..videorec import VideoRecorder

        if self.video_rec is not None:
            rec, self.video_rec = self.video_rec, None
            path = rec.close()
            self.rec_btn.configure(text="Record video")
            if path:
                self.app.say(f"Video saved ({rec.kind}): {path}")
            return
        self.video_rec = VideoRecorder(recordings_dir() / stamp("atv_video"), fps=25)
        self.rec_btn.configure(text="Stop recording")

    def close(self) -> None:
        self.stop()
        self.app.video_window = None
        self.destroy()
