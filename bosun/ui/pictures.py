"""Pictures tab: receive SSTV pictures from radio audio, an SDR signal or a WAV file."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np

from ..raster import png_bytes
from ..recorder import AUDIO_RATE, Demodulator, input_devices, recordings_dir, stamp
from ..sstv import BY_NAME, SSTVDecoder, read_wav
from .tips import tip

PAD = 6
SRC_RADIO = "Radio audio (sound input)"
SRC_SDR = "SDR: the selected signal"
SRC_FILE = "WAV file..."


class SDRAudioTap:
    """Demodulates the selected SDR signal and feeds a decoder (worker thread)."""

    def __init__(self, rate: float, center_hz: float, signal_hz: float, sink) -> None:
        self.demod = Demodulator(rate, signal_hz - center_hz, "FM", bandwidth_hz=6_000)
        self.sink = sink

    def write(self, iq) -> None:
        self.sink(self.demod.process(iq))


class PicturesTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=PAD)
        self.app = app
        self.decoder: SSTVDecoder | None = None
        self._stream = None
        self._tap = None
        self._q: queue.Queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._photo = None
        self._dirty = False
        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        ttk.Label(self, wraplength=820, justify="left", foreground="#555", text=(
            "Receives SSTV pictures (Martin, Scottie, Robot 36, PD90/120/180; the ISS uses "
            "PD120/PD180 on 145.800 MHz FM). Tune your radio or the SDR to the signal, "
            "choose where the audio comes from and press Start. Pictures save "
            "automatically to 'Bosun Recordings'.")).grid(row=0, column=0, columnspan=4,
                                                         sticky="w")
        ttk.Label(self, text="Audio from").grid(row=1, column=0, sticky="w", pady=PAD)
        self.source = tk.StringVar(value=SRC_RADIO)
        tip(ttk.Combobox(self, textvariable=self.source, state="readonly", width=28,
                         values=[SRC_RADIO, SRC_SDR, SRC_FILE]), "pic_source").grid(
            row=1, column=1, sticky="w", padx=PAD)
        self.device = tk.StringVar(value=app.settings.get("audio_input") or "")
        self.dev_box = tip(ttk.Combobox(self, textvariable=self.device, width=40), "audio_in")
        self.dev_box.grid(row=1, column=2, sticky="ew", padx=PAD)
        self.btn = tip(ttk.Button(self, text="Start", command=self.toggle), "pic_start")
        self.btn.grid(row=1, column=3)
        self.status = tk.StringVar(value="Idle.")
        ttk.Label(self, textvariable=self.status).grid(row=2, column=0, columnspan=4,
                                                       sticky="w")
        body = ttk.Frame(self)
        body.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=(PAD, 0))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(body, background="#111", highlightthickness=0,
                                width=640, height=496)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        side = ttk.Frame(body, padding=(PAD, 0, 0, 0))
        side.grid(row=0, column=1, sticky="ns")
        ttk.Label(side, text="Received").pack(anchor="w")
        self.gallery = tk.Listbox(side, width=34, height=18)
        self.gallery.pack(fill="y", expand=True)
        self.gallery.bind("<Double-Button-1>", self._show_saved)
        ttk.Button(side, text="Open folder", command=app._open_recordings).pack(
            fill="x", pady=(PAD, 0))
        self._saved: list = []
        with contextlib.suppress(Exception):
            self.dev_box.configure(values=input_devices())
        self.after(200, self._refresh)

    # ------------------------------------------------------------ decoder events
    def _new_decoder(self) -> SSTVDecoder:
        return SSTVDecoder(
            AUDIO_RATE,
            on_start=lambda m: self.app.post(self._started, m),
            on_line=lambda img, row: setattr(self, "_dirty", True),
            on_done=lambda img, m: self.app.post(self._done, img.copy(), m))

    def _started(self, mode) -> None:
        self.status.set(f"Receiving {mode.name} picture...")
        self.app.say(f"SSTV: receiving {mode.name}.")

    def _done(self, img: np.ndarray, mode) -> None:
        path = recordings_dir() / (stamp(f"sstv_{mode.name.replace(' ', '')}") + ".png")
        try:
            from PIL import Image
            Image.fromarray(img).save(path)
        except Exception:
            path = path.with_suffix(".ppm")
            with open(path, "wb") as fh:
                fh.write(f"P6 {img.shape[1]} {img.shape[0]} 255\n".encode() + img.tobytes())
        self._saved.insert(0, (path, img))
        self.gallery.insert(0, f"{time.strftime('%H:%M:%S')}  {mode.name}")
        self.status.set(f"Saved {path.name}. Listening for the next picture...")
        self.app.say(f"SSTV picture saved: {path}")
        self._render(img)

    # ------------------------------------------------------------ display
    def _render(self, img: np.ndarray) -> None:
        self._photo = tk.PhotoImage(data=png_bytes(img))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

    def _refresh(self) -> None:
        if self._dirty and self.decoder is not None and self.decoder.image is not None:
            self._dirty = False
            self._render(self.decoder.image)
        self.after(400, self._refresh)

    def _show_saved(self, _e=None) -> None:
        sel = self.gallery.curselection()
        if sel:
            self._render(self._saved[sel[0]][1])

    # ------------------------------------------------------------ sources
    def toggle(self) -> None:
        if self.decoder is not None:
            self.stop()
            return
        src = self.source.get()
        self.decoder = self._new_decoder()
        self._stop.clear()
        try:
            if src == SRC_FILE:
                path = filedialog.askopenfilename(parent=self, filetypes=[("WAV audio",
                                                                           "*.wav")])
                if not path:
                    self.decoder = None
                    return
                threading.Thread(target=self._run_file, args=(path,), daemon=True).start()
                self.status.set(f"Decoding {path}...")
            elif src == SRC_SDR:
                self._start_sdr()
            else:
                self._start_sound()
        except Exception as exc:
            self.decoder = None
            self.status.set(f"Cannot start: {exc}")
            return
        self.btn.configure(text="Stop")

    def _start_sound(self) -> None:
        import sounddevice as sd

        dev = self.device.get()
        dev_id = int(dev.split(":", 1)[0]) if dev and ":" in dev else None

        def cb(indata, _frames, _t, _status):
            with contextlib.suppress(queue.Full):
                self._q.put_nowait(indata[:, 0].copy())

        self._stream = sd.InputStream(device=dev_id, channels=1, samplerate=AUDIO_RATE,
                                      dtype="float32", blocksize=4096, callback=cb)
        self._stream.start()
        threading.Thread(target=self._pump, daemon=True).start()
        self.status.set("Listening for SSTV on the sound input...")

    def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                block = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            dec = self.decoder
            if dec is not None:
                dec.feed(block)

    def _start_sdr(self) -> None:
        sp = self.app.spectrum
        if sp is None or sp.source is None:
            raise RuntimeError("start the Spectrum first and click the SSTV signal")
        if sp.selected_hz is None:
            raise RuntimeError("click the SSTV signal on the Spectrum tab first")
        if sp._wide():
            raise RuntimeError("use a span of 2.4 MHz or less")
        src = sp.source
        self._tap = SDRAudioTap(src.rate, src.center_hz, sp.selected_hz,
                                lambda audio: self.decoder and self.decoder.feed(audio))
        sp.iq_taps.append(self._tap)
        self.status.set(f"Listening for SSTV at {sp.selected_hz / 1e6:.4f} MHz (SDR, FM)...")

    def _run_file(self, path: str) -> None:
        try:
            audio = read_wav(path, AUDIO_RATE)
        except Exception as exc:
            self.app.post(self.status.set, f"Cannot read {path}: {exc}")
            self.app.post(self.stop)
            return
        dec = self.decoder
        for k in range(0, len(audio), 8192):
            if self._stop.is_set() or dec is None:
                return
            dec.feed(audio[k:k + 8192])
        self.app.post(self.status.set, "Finished the file." if self._saved else
                      "No SSTV picture found in that file.")
        self.app.post(self.stop)

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        sp = self.app.spectrum
        if self._tap is not None and sp is not None and self._tap in sp.iq_taps:
            sp.iq_taps.remove(self._tap)
        self._tap = None
        self.decoder = None
        self.btn.configure(text="Start")
        if not self.status.get().startswith(("Saved", "Finished", "No SSTV")):
            self.status.set("Stopped.")

    def shutdown(self) -> None:
        self.stop()


__all__ = ["PicturesTab", "BY_NAME"]
