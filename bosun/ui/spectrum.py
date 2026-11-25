"""Spectrum tab: live spectrum + waterfall, detection, cognitive log, sweep, capture."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from PIL import ImageTk

from .. import chirp, dsp
from ..cognitive import CognitiveReceiver, Sweeper
from ..recorder import IQRecorder, SDRAudioRecorder, recordings_dir, stamp
from ..render import SpectrumView
from ..sources import list_sources, open_source
from .tips import tip

PAD = 6
SPANS = {"250 kHz": 0.25e6, "1 MHz": 1.024e6, "2 MHz": 2.048e6, "2.4 MHz": 2.4e6}
NFFT = 2048


class SpectrumTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=PAD)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.source = None
        self.view = SpectrumView(860, 380)
        self.cog = CognitiveReceiver()
        self.frames: queue.Queue = queue.Queue(maxsize=3)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.detections: list[dsp.Detection] = []
        self.selected_hz: float | None = None
        self.iq_rec = None
        self.audio_rec = None
        self._photo = None
        self._sweeping = False
        self._sweep_result = None
        self._build()
        self._opts: dict = {}
        self._sync_opts()
        self.after(100, self._tick)

    def _sync_opts(self) -> None:
        """Copy Tk settings into plain values for the worker threads (Tk is not
        thread-safe)."""
        self._opts = {"span": self.span.get(), "auto": bool(self.auto.get()),
                      "cog": bool(self.cognitive.get()), "sens": float(self.sens.get())}

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        settings = self.app.settings
        ttk.Label(bar, text="Source").pack(side="left")
        self.src_name = tk.StringVar(value=settings.get("sdr") or list_sources()[0])
        self.src_box = tip(ttk.Combobox(bar, textvariable=self.src_name, width=26,
                                        values=list_sources()), "source")
        self.src_box.pack(side="left", padx=(2, PAD))
        ttk.Label(bar, text="Centre MHz").pack(side="left")
        self.center = tk.StringVar(value=str(settings.get("sdr_center_mhz", 145.2)))
        e = tip(ttk.Entry(bar, textvariable=self.center, width=10), "center")
        e.pack(side="left", padx=(2, PAD))
        e.bind("<Return>", lambda _e: self.retune())
        ttk.Label(bar, text="Span").pack(side="left")
        self.span = tk.StringVar(value=settings.get("sdr_span", "2 MHz"))
        tip(ttk.Combobox(bar, textvariable=self.span, values=list(SPANS), width=8,
                         state="readonly"), "span").pack(side="left", padx=(2, PAD))
        ttk.Label(bar, text="Gain").pack(side="left")
        self.gain = tk.DoubleVar(value=float(settings.get("sdr_gain", 30)))
        g = tip(ttk.Scale(bar, from_=0, to=50, variable=self.gain, length=90), "gain")
        g.pack(side="left", padx=(2, PAD))
        g.bind("<ButtonRelease-1>", lambda _e: self._set_gain())
        self.run_btn = tip(ttk.Button(bar, text="Start", command=self.toggle), "run")
        self.run_btn.pack(side="left")

        det = ttk.Frame(self)
        det.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        self.auto = tk.BooleanVar(value=True)
        self.cognitive = tk.BooleanVar(value=True)
        tip(ttk.Checkbutton(det, text="Auto-detect signals", variable=self.auto),
            "auto_detect").pack(side="left")
        tip(ttk.Checkbutton(det, text="Cognitive receiver", variable=self.cognitive),
            "cognitive").pack(side="left", padx=PAD)
        ttk.Label(det, text="Sensitivity").pack(side="left")
        self.sens = tk.DoubleVar(value=0.5)
        tip(ttk.Scale(det, from_=0, to=1, variable=self.sens, length=80), "sensitivity").pack(
            side="left", padx=(2, PAD * 2))
        det = ttk.Frame(self)
        det.grid(row=2, column=0, sticky="ew", pady=(PAD, 0))
        tip(ttk.Button(det, text="Capture PNG", command=self.capture), "capture").pack(
            side="left")
        self.iq_btn = tip(ttk.Button(det, text="Record IQ", command=self.toggle_iq), "rec_iq")
        self.iq_btn.pack(side="left", padx=PAD)
        self.rec_mode = tk.StringVar(value="FM")
        tip(ttk.Combobox(det, textvariable=self.rec_mode, width=5, state="readonly",
                         values=["FM", "WFM", "AM", "USB", "LSB", "CW"]), "rec_mode").pack(
            side="left")
        self.audio_btn = tip(ttk.Button(det, text="Record audio", command=self.toggle_audio),
                             "rec_audio")
        self.audio_btn.pack(side="left", padx=(2, 0))

        body = ttk.PanedWindow(self, orient="vertical")
        body.grid(row=3, column=0, sticky="nsew", pady=(PAD, 0))
        self.canvas = tk.Canvas(body, height=380, background="#0c1624",
                                highlightthickness=0, cursor="crosshair")
        tip(self.canvas, "canvas")
        body.add(self.canvas, weight=3)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", lambda _e: self.readout.set(""))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Double-Button-1>", self._recenter)
        self.canvas.bind("<Configure>", self._resized)

        lower = ttk.Frame(body)
        body.add(lower, weight=2)
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(1, weight=1)
        self.readout = tk.StringVar()
        ttk.Label(lower, textvariable=self.readout, font=("TkFixedFont", 10)).grid(
            row=0, column=0, sticky="w")
        cols = ("freq", "type", "snr", "busy", "seen")
        self.table = ttk.Treeview(lower, columns=cols, show="headings", height=6)
        for c, label, w in (("freq", "Frequency (MHz)", 120), ("type", "Type", 150),
                            ("snr", "Best SNR", 70), ("busy", "Busy", 60),
                            ("seen", "Status", 160)):
            self.table.heading(c, text=label)
            self.table.column(c, width=w, anchor="w")
        self.table.tag_configure("new", foreground="#d6336c")
        self.table.tag_configure("off", foreground="#888")
        self.table.grid(row=1, column=0, sticky="nsew")
        tip(self.table, "signals")
        self.table.bind("<Double-Button-1>", self._pick_row)

        side = ttk.Frame(lower, padding=(PAD, 0, 0, 0))
        side.grid(row=1, column=1, sticky="ns")
        tip(ttk.Button(side, text="Export CSV", command=self.export_csv), "export_csv").pack(
            fill="x")
        tip(ttk.Button(side, text="Save as channels", command=self.export_chirp),
            "export_chirp").pack(fill="x", pady=2)
        ttk.Button(side, text="Clear log", command=self.cog.reset).pack(fill="x")
        ttk.Separator(side).pack(fill="x", pady=PAD)
        ttk.Label(side, text="Sweep MHz").pack(anchor="w")
        row = ttk.Frame(side)
        row.pack(fill="x")
        self.sw_start = tk.StringVar(value="144")
        self.sw_stop = tk.StringVar(value="148")
        tip(ttk.Entry(row, textvariable=self.sw_start, width=7), "sweep_start").pack(
            side="left")
        ttk.Label(row, text="-").pack(side="left")
        tip(ttk.Entry(row, textvariable=self.sw_stop, width=7), "sweep_stop").pack(
            side="left")
        self.sweep_btn = tip(ttk.Button(side, text="Sweep", command=self.toggle_sweep),
                             "sweep")
        self.sweep_btn.pack(fill="x", pady=2)

    # ---------------------------------------------------------------- source
    def _center_hz(self) -> float:
        return float(self.center.get().replace(",", ".")) * 1e6

    def toggle(self) -> None:
        if self._worker is not None:
            self.stop()
            return
        try:
            self.source = open_source(self.src_name.get(), self._center_hz(),
                                      SPANS.get(self.span.get(), 2.048e6), self.gain.get())
        except Exception as exc:
            self.app.say(f"Could not start {self.src_name.get()}: {exc}")
            return
        self._stop.clear()
        self._sync_opts()
        self.cog.reset()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()
        self.run_btn.configure(text="Stop")
        self.app.say(f"Spectrum running from {self.source.name}.")

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(2)
        self._worker = None
        self._close_recorders()
        if self.source is not None:
            self.source.close()
            self.source = None
        self.run_btn.configure(text="Start")

    def retune(self, hz: float | None = None) -> None:
        if hz is not None:
            self.center.set(f"{hz / 1e6:.4f}")
        if self.source is not None:
            try:
                self.source.tune(self._center_hz())
            except Exception as exc:
                self.app.say(f"Retune failed: {exc}")

    def _set_gain(self) -> None:
        if self.source is not None:
            try:
                self.source.set_gain(self.gain.get())
            except Exception as exc:
                self.app.say(f"Gain: {exc}")

    def _run(self) -> None:
        span_name = self._opts["span"]
        while not self._stop.is_set():
            src = self.source
            opts = self._opts
            if src is None:
                break
            want = SPANS.get(opts["span"], src.rate)
            if want != src.rate and opts["span"] != span_name:
                span_name = opts["span"]
                src.rate = want
                if hasattr(src, "_dev") and src._dev is not None:
                    with contextlib.suppress(Exception):
                        src._dev.set_sample_rate(want)
            try:
                iq = src.read(NFFT * 8)
            except Exception as exc:
                self.app.post(self.app.say, f"SDR read failed: {exc}")
                break
            for rec in (self.iq_rec, self.audio_rec):
                if rec is not None:
                    with contextlib.suppress(Exception):
                        rec.write(iq)
            off, p = dsp.psd(iq, src.rate, NFFT)
            dets = []
            floor = None
            if opts["auto"]:
                if opts["cog"]:
                    self.cog.sensitivity = opts["sens"]
                    dets = self.cog.process(off, p, src.center_hz)
                    floor = None if self.cog.floor is None else self.cog.floor.copy()
                else:
                    dets = dsp.detect(off, p, src.center_hz,
                                      threshold_db=12 - 8 * opts["sens"])
            with contextlib.suppress(queue.Full):
                self.frames.put_nowait((off + src.center_hz, p, dets, floor))
            if src.name.startswith("Demo"):
                time.sleep(0.05)

    # ---------------------------------------------------------------- display
    def _tick(self) -> None:
        self._sync_opts()
        latest = None
        try:
            while True:
                latest = self.frames.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            freqs, p, self.detections, floor = latest
            self.view.push(freqs, p)
            self._floor = floor
            self._draw()
        self._ticks = getattr(self, "_ticks", 0) + 1
        if self._ticks % 12 == 0 and self.cog.signals:
            self._refresh_table()
        self.after(80, self._tick)

    def _draw(self) -> None:
        new = {s.center_hz for s in self.cog.new_signals()} if self.cognitive.get() else set()
        title = ""
        if self.source is not None:
            title = f"{self.source.name}  centre {self.source.center_hz / 1e6:.4f} MHz"
        img = self.view.image(detections=self.detections, floor_db=getattr(self, "_floor", None),
                              title=title, marker_hz=self.selected_hz,
                              new_hz=self._near_new(new))
        self._photo = self._to_photo(img)
        self.frames_drawn = getattr(self, "frames_drawn", 0) + 1
        self.canvas.delete("img")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="img")

    _use_ppm = False

    def _to_photo(self, img):
        """PIL image to a Tk photo. Falls back to raw PPM data when Pillow's Tk
        bridge is unavailable (e.g. some packaged builds)."""
        if not self._use_ppm:
            try:
                return ImageTk.PhotoImage(img)
            except Exception:
                SpectrumTab._use_ppm = True
        data = f"P6 {img.width} {img.height} 255 ".encode() + img.convert("RGB").tobytes()
        return tk.PhotoImage(data=data, format="ppm")

    def _near_new(self, new_centres: set) -> set:
        out = set()
        for d in self.detections:
            if any(abs(d.center_hz - c) < max(d.bandwidth_hz, 2000) for c in new_centres):
                out.add(d.center_hz)
        return out

    def _resized(self, event) -> None:
        self.view.resize(event.width, event.height)

    def _refresh_table(self) -> None:
        self.table.delete(*self.table.get_children())
        new = {id(s) for s in self.cog.new_signals()}
        for s in self.cog.ranked()[:200]:
            ago = time.time() - s.last_seen
            status = "on now" if s.active else f"last heard {ago:.0f}s ago"
            if id(s) in new:
                status = "NEW - " + status
            self.table.insert("", "end", iid=f"{s.center_hz:.0f}", values=(
                f"{s.center_hz / 1e6:.5f}", s.kind, f"{s.best_snr_db:.0f} dB",
                f"{s.activity:.0%}", status),
                tags=("new",) if id(s) in new else (() if s.active else ("off",)))

    # ---------------------------------------------------------------- hover / click
    def _describe_at(self, hz: float) -> str:
        level = self.view.level_at(hz)
        text = f"{hz / 1e6:.5f} MHz"
        if level is not None:
            text += f"   {level:.0f} dB"
        for d in self.detections:
            if abs(d.center_hz - hz) <= max(d.bandwidth_hz / 2, 1500):
                text += (f"   >> {d.kind}: {d.hint}. ~{d.bandwidth_hz / 1e3:.1f} kHz wide, "
                         f"{d.snr_db:.0f} dB above noise")
                break
        return text

    def _hover(self, event) -> None:
        hz = self.view.x_to_hz(event.x)
        self.readout.set(self._describe_at(hz) if hz else "")

    def _click(self, event) -> None:
        hz = self.view.x_to_hz(event.x)
        if hz is None:
            return
        for d in self.detections:  # snap to a nearby signal
            if abs(d.center_hz - hz) <= max(d.bandwidth_hz / 2, 3000):
                hz = d.center_hz
                self.rec_mode.set(chirp.record_mode_for(d.kind))
                break
        self.select(hz)

    def select(self, hz: float) -> None:
        self.selected_hz = hz
        self.app.say(f"Selected {hz / 1e6:.5f} MHz.")
        self.app.tune_radio(hz)

    def _recenter(self, event) -> None:
        hz = self.view.x_to_hz(event.x)
        if hz:
            self.retune(hz)

    def _pick_row(self, _e=None) -> None:
        sel = self.table.selection()
        if sel:
            hz = float(sel[0])
            if self.source is not None and abs(hz - self.source.center_hz) > self.source.rate / 2:
                self.retune(hz)
            self.select(hz)

    # ---------------------------------------------------------------- output
    def capture(self) -> None:
        path = recordings_dir() / (stamp("spectrum") + ".png")
        self.view.capture(str(path), detections=self.detections,
                          floor_db=getattr(self, "_floor", None), marker_hz=self.selected_hz,
                          title=self.source.name if self.source else "")
        self.app.say(f"Saved {path}")

    def toggle_iq(self) -> None:
        if self.iq_rec is not None:
            path = self.iq_rec.close()
            self.iq_rec = None
            self.iq_btn.configure(text="Record IQ")
            self.app.say(f"IQ saved: {path}")
            return
        if self.source is None:
            self.app.say("Start the spectrum first.")
            return
        self.iq_rec = IQRecorder(self.source.center_hz, self.source.rate,
                                 description=f"Bosun capture from {self.source.name}")
        self.iq_btn.configure(text="Stop IQ")
        self.app.say("Recording IQ...")

    def toggle_audio(self) -> None:
        if self.audio_rec is not None:
            path = self.audio_rec.close()
            self.audio_rec = None
            self.audio_btn.configure(text="Record audio")
            self.app.say(f"Audio saved: {path}")
            return
        if self.source is None or self.selected_hz is None:
            self.app.say("Start the spectrum and click a signal first.")
            return
        if abs(self.selected_hz - self.source.center_hz) > self.source.rate / 2:
            self.app.say("The selected signal is outside the current view.")
            return
        self.audio_rec = SDRAudioRecorder(self.source.rate, self.source.center_hz,
                                          self.selected_hz, self.rec_mode.get())
        self.audio_btn.configure(text="Stop audio")
        self.app.say(f"Recording {self.rec_mode.get()} audio at "
                     f"{self.selected_hz / 1e6:.5f} MHz...")

    def _close_recorders(self) -> None:
        if self.iq_rec is not None:
            self.toggle_iq()
        if self.audio_rec is not None:
            self.toggle_audio()

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", initialdir=recordings_dir(),
            initialfile=stamp("signals") + ".csv", filetypes=[("CSV", "*.csv")])
        if path:
            n = self.cog.export_csv(path)
            self.app.say(f"Saved {n} signals to {path}")

    def export_chirp(self) -> None:
        sigs = self.cog.ranked()
        if not sigs:
            self.app.say("No signals logged yet. Start the spectrum with Cognitive receiver on.")
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", initialdir=recordings_dir(),
            initialfile=stamp("channels") + ".csv", filetypes=[("CHIRP CSV", "*.csv")])
        if path:
            n = chirp.write_csv(path, [
                {"frequency_hz": s.center_hz, "name": f"{s.center_hz / 1e6:.4f}",
                 "mode": s.kind, "comment": f"{s.kind}; busy {s.activity:.0%}"}
                for s in sigs])
            self.app.say(f"Saved {n} channels for CHIRP to {path}")

    # ---------------------------------------------------------------- sweep
    def toggle_sweep(self) -> None:
        if self._sweeping:
            self._sweeping = False
            return
        try:
            lo = float(self.sw_start.get()) * 1e6
            hi = float(self.sw_stop.get()) * 1e6
        except ValueError:
            self.app.say("Sweep range must be numbers in MHz.")
            return
        was_running = self._worker is not None
        if was_running:
            self.stop()
        try:
            src = open_source(self.src_name.get(), lo, SPANS.get(self.span.get(), 2.048e6),
                              self.gain.get())
        except Exception as exc:
            self.app.say(f"Could not start sweep: {exc}")
            return
        self._sweeping = True
        self.sweep_btn.configure(text="Stop sweep")
        self.app.say(f"Sweeping {lo / 1e6:g}-{hi / 1e6:g} MHz...")

        def work():
            try:
                sw = Sweeper(src, lo, hi, nfft=NFFT)
                passes = 0
                while self._sweeping:
                    f, p = sw.sweep(settle_s=0.0 if src.name.startswith("Demo") else 0.05,
                                    stop_flag=lambda: not self._sweeping)
                    if not len(f):
                        break
                    dets = dsp.detect(f, p, 0.0, threshold_db=12 - 8 * self._opts["sens"])
                    self.cog._track(dets)
                    passes += 1
                    with contextlib.suppress(queue.Full):
                        self.frames.put_nowait((f, p, dets, None))
                    self.app.post(self.app.say, f"Sweep pass {passes}: {len(dets)} signals "
                                                f"across {len(sw.centers)} steps.")
            except Exception as exc:
                self.app.post(self.app.say, f"Sweep failed: {exc}")
            finally:
                src.close()
                self._sweeping = False
                self.app.post(self.sweep_btn.configure, text="Sweep")

        threading.Thread(target=work, daemon=True).start()

    def shutdown(self) -> None:
        self._sweeping = False
        self.stop()


__all__ = ["SpectrumTab", "np"]
