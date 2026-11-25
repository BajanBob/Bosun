"""Audio tab: record the radio's audio from a sound input; export channel lists."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from .. import chirp
from ..recorder import SoundCardRecorder, input_devices, recordings_dir, stamp
from .tips import tip

PAD = 6


class AudioTab(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=PAD)
        self.app = app
        self.rec: SoundCardRecorder | None = None
        self.columnconfigure(1, weight=1)

        ttk.Label(self, wraplength=760, justify="left", foreground="#555", text=(
            "Record what your radio hears. Choose the radio's USB audio device, or the "
            "line-in / mic-in its speaker or data jack is wired to. Works with every radio, "
            "including ones with no computer control such as the Radtel RT-950 Pro.")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(self, text="Input").grid(row=1, column=0, sticky="w", pady=PAD)
        self.device = tk.StringVar(value=app.settings.get("audio_input") or "")
        self.dev_box = tip(ttk.Combobox(self, textvariable=self.device), "audio_in")
        self.dev_box.grid(row=1, column=1, sticky="ew", padx=PAD)
        ttk.Button(self, text="Refresh", command=self.refresh).grid(row=1, column=2)
        self.btn = tip(ttk.Button(self, text="Start recording", command=self.toggle),
                       "audio_rec")
        self.btn.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.meter = ttk.Progressbar(self, maximum=1.0)
        self.meter.grid(row=3, column=0, columnspan=3, sticky="ew", pady=PAD)
        self.info = tk.StringVar(value="Not recording.")
        ttk.Label(self, textvariable=self.info).grid(row=4, column=0, columnspan=3,
                                                     sticky="w")
        tip(ttk.Button(self, text="Open recordings folder", command=app._open_recordings),
            "open_folder").grid(row=5, column=0, sticky="w", pady=PAD)

        chan = ttk.LabelFrame(self, text="Channel list (CHIRP CSV)", padding=PAD)
        chan.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=PAD)
        chan.columnconfigure(0, weight=1)
        self.rowconfigure(6, weight=1)
        ttk.Label(chan, wraplength=740, justify="left", foreground="#555", text=(
            "One channel per line: frequency in MHz, then an optional name and mode, e.g. "
            "'145.500 Calling FM'. Saved as CHIRP CSV for handhelds and mobiles (import "
            "in CHIRP, or retype into the maker's programming software).")).grid(
            row=0, column=0, sticky="w")
        self.channels = tk.Text(chan, height=8)
        self.channels.grid(row=1, column=0, sticky="nsew", pady=PAD)
        chan.rowconfigure(1, weight=1)
        tip(ttk.Button(chan, text="Save channel list...", command=self.export),
            "export_chirp").grid(row=2, column=0, sticky="w")
        self.refresh()

    def refresh(self) -> None:
        try:
            devs = input_devices()
        except Exception as exc:
            devs = []
            self.info.set(str(exc))
        self.dev_box.configure(values=devs)
        if devs and not self.device.get():
            self.device.set(devs[0])

    def toggle(self) -> None:
        if self.rec is not None:
            path = self.rec.close()
            self.rec = None
            self.btn.configure(text="Start recording")
            self.meter["value"] = 0
            self.info.set(f"Saved {path}")
            self.app.say(f"Audio saved: {path}")
            return
        try:
            self.rec = SoundCardRecorder(self.device.get() or None, label="radio")
        except Exception as exc:
            self.info.set(f"Cannot record: {exc}")
            return
        self.btn.configure(text="Stop recording")
        self._update()

    def _update(self) -> None:
        if self.rec is None:
            return
        self.meter["value"] = min(1.0, self.rec.level * 4)
        self.info.set(f"Recording... {self.rec.seconds:.0f} s")
        self.after(150, self._update)

    def export(self) -> None:
        rows = []
        for line in self.channels.get("1.0", "end").splitlines():
            parts = line.split()
            if not parts:
                continue
            try:
                hz = float(parts[0].replace(",", ".")) * 1e6
            except ValueError:
                self.app.say(f"Skipped line (no frequency): {line}")
                continue
            mode = parts[-1] if len(parts) > 1 and parts[-1].upper() in chirp.CHIRP_MODES else ""
            name = " ".join(parts[1:-1] if mode else parts[1:])
            rows.append({"frequency_hz": hz, "name": name, "mode": mode or "FM"})
        if not rows:
            self.app.say("Type at least one frequency first.")
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", initialdir=recordings_dir(),
            initialfile=stamp("channels") + ".csv", filetypes=[("CHIRP CSV", "*.csv")])
        if path:
            self.app.say(f"Saved {chirp.write_csv(path, rows)} channels to {path}")

    def shutdown(self) -> None:
        if self.rec is not None:
            self.rec.close()
            self.rec = None
