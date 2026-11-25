"""Bosun desktop app (Tkinter). Runs radio I/O on worker threads."""

from __future__ import annotations

import contextlib
import os
import pathlib
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

from . import config
from .control import (
    Controller,
    default_baud,
    format_status,
    modes_for,
    serial_ports,
)
from .radios import registry
from .sdr import catalogue as sdrcat
from .ui.tips import Tooltip, tip
from .version import __version__

PAD = 6
ICON = pathlib.Path(__file__).with_name("assets") / "bosun.png"


def open_folder(path: pathlib.Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class BosunApp(ttk.Frame):
    def __init__(self, root: tk.Tk, controller: Controller | None = None,
                 first_run_wizard: bool = True) -> None:
        super().__init__(root, padding=PAD * 2)
        self.root = root
        self.ctl = controller or Controller()
        self.settings = config.read_settings()
        Tooltip.enabled = bool(self.settings.get("hover_tips", True))
        self._results: queue.Queue = queue.Queue()
        root.title(f"Bosun {__version__}")
        root.minsize(900, 640)
        try:
            self._icon = tk.PhotoImage(file=str(ICON))
            root.iconphoto(True, self._icon)
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        from .ui.banner import Banner
        self.banner = Banner(self)
        self.banner.grid(row=0, column=0, sticky="ew", pady=(0, PAD))
        self.banner.hide()
        self._build_menu()
        self._build_connection()
        self.nb = ttk.Notebook(self)
        self.nb.grid(row=2, column=0, sticky="nsew", pady=(PAD, 0))
        self.nb.add(self._build_control(self.nb), text="Control")
        try:
            from .ui.spectrum import SpectrumTab
            self.spectrum = SpectrumTab(self.nb, self)
            self.nb.add(self.spectrum, text="Spectrum")
        except Exception as exc:  # Pillow missing etc.
            self.spectrum = None
            err = ttk.Label(self.nb, text=f"Spectrum unavailable: {exc}", padding=20)
            self.nb.add(err, text="Spectrum")
        self.nb.add(self._build_scan(self.nb), text="Scan")
        from .ui.audio import AudioTab
        self.audio_tab = AudioTab(self.nb, self)
        self.nb.add(self.audio_tab, text="Audio")
        from .ui.pictures import PicturesTab
        self.pictures = PicturesTab(self.nb, self)
        self.nb.add(self.pictures, text="Pictures")
        self.nb.add(self._build_devices(self.nb), text="Devices")
        self.nb.add(self._build_catalogue(self.nb), text="Radios")
        self.message = tk.StringVar(value="Not connected.")
        ttk.Label(self, textvariable=self.message, anchor="w").grid(
            row=3, column=0, sticky="ew", pady=(PAD, 0))
        self._refresh_ports()
        self._apply_settings()
        self.after(50, self._drain)
        self.watcher = None
        self.screens: list = []
        self.video_window = None
        if self.settings.get("auto_detect", True):
            self.after(500, self.start_watching)
        if first_run_wizard and not self.settings.get("setup_done"):
            self.after(300, self.open_wizard)

    # ---------- layout ----------
    def _build_menu(self) -> None:
        bar = tk.Menu(self.root)
        setup = tk.Menu(bar, tearoff=False)
        setup.add_command(label="Setup wizard...", command=self.open_wizard)
        setup.add_command(label="Detect my radio now", command=self.detect_now)
        setup.add_command(label="Open recordings folder", command=self._open_recordings)
        setup.add_separator()
        setup.add_command(label="Quit", command=self.quit_app)
        bar.add_cascade(label="Setup", menu=setup)
        view = tk.Menu(bar, tearoff=False)
        view.add_command(label="Faceplate (touch screen)", command=self.open_faceplate)
        view.add_command(label="Video (analogue TV / FPV)", command=self.open_video)
        view.add_command(label="Second screen...", command=self.open_second_screen)
        bar.add_cascade(label="View", menu=view)
        helpm = tk.Menu(bar, tearoff=False)
        self.tips_var = tk.BooleanVar(value=Tooltip.enabled)
        helpm.add_checkbutton(label="Show hover tips", variable=self.tips_var,
                              command=self._toggle_tips)
        self.watch_var = tk.BooleanVar(value=self.settings.get("auto_detect", True))
        helpm.add_checkbutton(label="Watch for plugged-in radios and SDRs",
                              variable=self.watch_var, command=self._toggle_watch)
        helpm.add_command(label="About Bosun", command=lambda: self.say(
            f"Bosun {__version__}: radio control, spectrum, detection and recording. "
            "MIT licence."))
        bar.add_cascade(label="Help", menu=helpm)
        self.root.configure(menu=bar)

    def _build_connection(self) -> None:
        box = ttk.LabelFrame(self, text="Connection", padding=PAD)
        box.grid(row=1, column=0, sticky="ew")
        for c in (1, 3):
            box.columnconfigure(c, weight=1)

        ttk.Label(box, text="Radio").grid(row=0, column=0, sticky="w")
        names = self._picker_names()
        self.model = tk.StringVar(value=names[0])
        self.model_box = tip(ttk.Combobox(box, textvariable=self.model, values=names,
                                          state="readonly"), "radio")
        self.model_box.grid(row=0, column=1, sticky="ew", padx=PAD)
        self.model_box.bind("<<ComboboxSelected>>", self._model_changed)

        self.link = tk.StringVar(value="serial")
        links = ttk.Frame(box)
        links.grid(row=0, column=2, columnspan=2, sticky="w")
        tip(ttk.Radiobutton(links, text="USB / serial", value="serial", variable=self.link,
                            command=self._link_changed), "link_serial").pack(side="left")
        tip(ttk.Radiobutton(links, text="Network (TCP)", value="tcp", variable=self.link,
                            command=self._link_changed), "link_tcp").pack(side="left",
                                                                           padx=PAD)

        self.serial_row = ttk.Frame(box)
        self.serial_row.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(PAD, 0))
        self.serial_row.columnconfigure(1, weight=1)
        ttk.Label(self.serial_row, text="Port").grid(row=0, column=0, sticky="w")
        self.port = tk.StringVar()
        self.port_box = tip(ttk.Combobox(self.serial_row, textvariable=self.port), "port")
        self.port_box.grid(row=0, column=1, sticky="ew", padx=PAD)
        tip(ttk.Button(self.serial_row, text="Refresh", command=self._refresh_ports),
            "refresh").grid(row=0, column=2)
        ttk.Label(self.serial_row, text="Baud").grid(row=0, column=3, padx=(PAD * 2, 0))
        self.baud = tk.StringVar(value=str(default_baud(self.model.get())))
        tip(ttk.Entry(self.serial_row, textvariable=self.baud, width=8), "baud").grid(
            row=0, column=4, padx=PAD)

        self.tcp_row = ttk.Frame(box)
        self.tcp_row.columnconfigure(1, weight=1)
        ttk.Label(self.tcp_row, text="Host / IP").grid(row=0, column=0, sticky="w")
        self.host = tk.StringVar()
        tip(ttk.Entry(self.tcp_row, textvariable=self.host), "host").grid(
            row=0, column=1, sticky="ew", padx=PAD)
        ttk.Label(self.tcp_row, text="TCP port").grid(row=0, column=2)
        self.tcp_port = tk.StringVar()
        tip(ttk.Entry(self.tcp_row, textvariable=self.tcp_port, width=8), "tcp_port").grid(
            row=0, column=3, padx=PAD)

        self.connect_btn = tip(ttk.Button(box, text="Connect", command=self._toggle_connect),
                               "connect")
        self.connect_btn.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(PAD, 0))

    def _build_control(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Frequency (MHz)").grid(row=0, column=0, sticky="w")
        self.freq = tk.StringVar()
        e = tip(ttk.Entry(f, textvariable=self.freq), "freq")
        e.grid(row=0, column=1, sticky="ew", padx=PAD)
        e.bind("<Return>", lambda _e: self._tune())
        ttk.Label(f, text="Mode").grid(row=0, column=2)
        self.mode = tk.StringVar()
        self.mode_box = tip(ttk.Combobox(f, textvariable=self.mode, state="readonly",
                                         width=8), "mode")
        self.mode_box.grid(row=0, column=3, padx=PAD)
        tip(ttk.Button(f, text="Tune", command=self._tune), "tune").grid(row=0, column=4)

        levels = ttk.LabelFrame(f, text="Levels (%)", padding=PAD)
        levels.grid(row=1, column=0, columnspan=5, sticky="ew", pady=PAD)
        levels.columnconfigure(1, weight=1)
        self.levels = {}
        for i, (key, text) in enumerate((("af", "AF gain"), ("rf", "RF gain"),
                                         ("squelch", "Squelch"))):
            ttk.Label(levels, text=text).grid(row=i, column=0, sticky="w")
            var = tk.DoubleVar(value=50)
            s = tip(ttk.Scale(levels, from_=0, to=100, variable=var), key)
            s.grid(row=i, column=1, sticky="ew", padx=PAD)
            s.bind("<ButtonRelease-1>", lambda _e, k=key: self._set_level(k))
            val = ttk.Label(levels, width=4)
            val.grid(row=i, column=2)
            var.trace_add("write", lambda *_a, v=var, lab=val: lab.configure(
                text=f"{v.get():.0f}"))
            var.set(50)
            self.levels[key] = var

        tip(ttk.Button(f, text="Read status", command=self._refresh), "status").grid(
            row=2, column=0, sticky="w")
        self.status = tk.Text(f, height=6, state="disabled", wrap="word")
        self.status.grid(row=3, column=0, columnspan=5, sticky="nsew", pady=(PAD, 0))
        f.rowconfigure(3, weight=1)
        self._model_changed()
        return f

    def _build_scan(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        f.columnconfigure(1, weight=1)
        f.columnconfigure(3, weight=1)
        self.scan_vars = {}
        for i, (key, text, default) in enumerate((
                ("start", "Start (MHz)", ""), ("stop", "Stop (MHz)", ""),
                ("step", "Step (kHz)", "25"), ("dwell", "Dwell (s)", "0.6"))):
            r, c = divmod(i, 2)
            ttk.Label(f, text=text).grid(row=r, column=c * 2, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            tip(ttk.Entry(f, textvariable=var), f"scan_{key}").grid(
                row=r, column=c * 2 + 1, sticky="ew", padx=PAD)
            self.scan_vars[key] = var
        self.scan_btn = tip(ttk.Button(f, text="Start scan", command=self._toggle_scan),
                            "scan_go")
        self.scan_btn.grid(row=2, column=0, columnspan=4, sticky="ew", pady=PAD)
        self.scan_now = tk.StringVar(value="Idle")
        ttk.Label(f, textvariable=self.scan_now).grid(row=3, column=0, columnspan=4,
                                                      sticky="w")
        self.hits = tip(tk.Listbox(f, height=10), "hits")
        self.hits.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=(PAD, 0))
        self.hits.bind("<Double-Button-1>", self._tune_to_hit)
        f.rowconfigure(4, weight=1)
        return f

    def _build_devices(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        tip(ttk.Button(f, text="Scan for devices", command=self._probe), "probe").pack(
            anchor="w")
        self.devices = tk.Text(f, height=12, state="disabled")
        self.devices.pack(fill="both", expand=True, pady=(PAD, 0))
        return f

    def _build_catalogue(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        cols = ("vendor", "model", "control", "bands", "modes")
        tree = ttk.Treeview(f, columns=cols, show="headings")
        for c, label, w in (("vendor", "Maker", 80), ("model", "Model", 120),
                            ("control", "Control", 140), ("bands", "Bands (MHz)", 260),
                            ("modes", "Modes", 260)):
            tree.heading(c, text=label)
            tree.column(c, width=w, anchor="w")
        for e in sorted(registry.catalogue(), key=lambda e: (e["vendor"], e["model"])):
            bands = ", ".join(f"{lo:g}-{hi:g}" for lo, hi in e["bands_mhz"])
            tree.insert("", "end", values=(e["vendor"], e["model"], e["control"], bands,
                                           " ".join(e["modes"])))
        for e in sdrcat.catalogue():
            bands = ", ".join(f"{lo:g}-{hi:g}" for lo, hi in e["bands_mhz"])
            tree.insert("", "end", values=(e["vendor"], e["model"], e["control"], bands,
                                           " ".join(e["modes"])))
        tree.pack(fill="both", expand=True)
        ttk.Label(f, foreground="#555", wraplength=760, justify="left", text=(
            "Built in: Bosun talks to the radio directly. Profile: you copy the commands "
            "from the radio's remote-control manual once (Setup wizard). Audio only: no PC "
            "control; record its audio and export channel lists. SDR receiver: receive "
            "only; pick it as the Radio and press Connect to start it on the Spectrum "
            "tab.")).pack(anchor="w", pady=PAD)
        return f

    # ---------- plumbing ----------
    def _bg(self, fn, *args, done=None, fail=None) -> None:
        """Run fn(*args) on a worker thread; done(result) or fail(exc) runs on the UI thread."""
        def work():
            try:
                self._results.put((done, fn(*args), None, fail))
            except Exception as exc:
                self._results.put((done, None, exc, fail))
        threading.Thread(target=work, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                done, result, exc, fail = self._results.get_nowait()
                if exc is not None:
                    self.message.set(f"Error: {exc}")
                    if fail is not None:
                        fail(exc)
                elif done is not None:
                    done(result)
        except queue.Empty:
            pass
        self.after(50, self._drain)

    def post(self, fn, *args, **kwargs) -> None:
        """Run fn on the UI thread (safe from worker threads)."""
        self._results.put((lambda _r: fn(*args, **kwargs), None, None, None))

    _post = post

    def say(self, text: str) -> None:
        self.message.set(text)

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ---------- settings / wizard ----------
    def _apply_settings(self) -> None:
        s = self.settings
        if s.get("model") in registry.DRIVERS:
            self.model.set(s["model"])
            self._model_changed()
        if s.get("tcp"):
            self.link.set("tcp")
            host, _, port = s["tcp"].partition(":")
            self.host.set(host)
            self.tcp_port.set(port)
        elif s.get("port"):
            self.port.set(s["port"])
        if s.get("baud"):
            self.baud.set(str(s["baud"]))
        self._link_changed()

    def open_wizard(self) -> None:
        from .ui.wizard import SetupWizard

        def done(_updates, path):
            self.settings = config.read_settings()
            Tooltip.enabled = bool(self.settings.get("hover_tips", True))
            self.tips_var.set(Tooltip.enabled)
            self.model_box.configure(values=self._picker_names())
            self._apply_settings()
            if self.spectrum is not None and self.settings.get("sdr"):
                self.spectrum.src_name.set(self.settings["sdr"])
            if self.settings.get("audio_input"):
                self.audio_tab.device.set(self.settings["audio_input"])
            self.say(f"Settings saved to {path}. Press Connect.")

        SetupWizard(self.root, on_done=done)

    def _toggle_tips(self) -> None:
        Tooltip.enabled = bool(self.tips_var.get())
        with contextlib.suppress(Exception):
            config.save_settings({"hover_tips": Tooltip.enabled})

    def _open_recordings(self) -> None:
        from .recorder import recordings_dir
        open_folder(recordings_dir())

    # ---------- faceplate ----------
    def open_faceplate(self, full_screen: bool = False):
        from .ui.faceplate import Faceplate

        if getattr(self, "faceplate", None) is not None:
            self.faceplate.lift()
            return self.faceplate
        self.faceplate = Faceplate(self)
        if full_screen:
            self.faceplate.after(200, lambda: self.faceplate.attributes("-fullscreen", True))
        return self.faceplate

    def open_video(self):
        from .ui.video import VideoWindow

        if getattr(self, "video_window", None) is not None:
            self.video_window.lift()
            return self.video_window
        self.video_window = VideoWindow(self)
        return self.video_window

    def open_second_screen(self) -> None:
        from .ui.screens import SecondScreenDialog

        SecondScreenDialog(self)

    # ---------- automatic device detection ----------
    def start_watching(self) -> None:
        from .detect import DeviceWatcher

        if self.watcher is not None:
            return
        self.watcher = DeviceWatcher(
            on_port_added=lambda info: self.post(self._port_added, info),
            on_port_removed=lambda info: self.post(self._port_removed, info),
            on_sdr_added=lambda name: self.post(self._sdr_added, name),
            on_sdr_removed=lambda name: self.post(self._sdr_removed, name))
        threading.Thread(target=self.watcher.start, daemon=True, name="watch-start").start()

    def stop_watching(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None

    def _toggle_watch(self) -> None:
        on = bool(self.watch_var.get())
        (self.start_watching if on else self.stop_watching)()
        with contextlib.suppress(Exception):
            config.save_settings({"auto_detect": on})
        self.say("Watching for new devices." if on else "Device watching is off.")

    def _port_added(self, info) -> None:
        self._refresh_ports()
        if info.is_programming_cable:
            self.banner.show(
                f"A programming cable was plugged in on {info.label()}. Radios that use "
                "these (e.g. Radtel RT-950 Pro, Baofeng) have no live computer control: "
                "use the Audio tab to record them and save channel lists for CHIRP.",
                [("Open Audio tab", lambda: self.nb.select(self.audio_tab))], kind="warn")
            return
        if self.ctl.connected:
            self.banner.show(f"New device on {info.label()}. Disconnect first to use it.",
                             [("Use this port", lambda: self.port.set(info.device))])
            return
        self.banner.show(f"New device on {info.label()}. Checking whether it is a radio...")
        self._identify(info)

    def _identify(self, info) -> None:
        from .detect import identify

        def done(hit):
            if hit is None:
                self.port.set(info.device)
                self.banner.show(
                    f"{info.label()} did not answer as a radio. If it is your radio, turn "
                    "on CAT / CI-V (USB) in the radio's menu and switch it on, then try "
                    "again. It may also be another kind of device.",
                    [("Try again", lambda: self._port_added(info)),
                     ("Use this port anyway", lambda: self.port.set(info.device))],
                    kind="warn")
                return
            self.banner.show(
                f"Found {registry.get(hit.model).vendor} {hit.model} on {hit.port} at "
                f"{hit.baud} baud ({hit.detail}).",
                [("Connect", lambda: self._use_detected(hit, connect=True)),
                 ("Just select it", lambda: self._use_detected(hit, connect=False))],
                kind="ok")

        self._bg(identify, info.device, done=done,
                 fail=lambda exc: self.banner.show(f"Could not check {info.device}: {exc}",
                                                   kind="warn"))

    def _use_detected(self, hit, connect: bool) -> None:
        self.banner.hide()
        self.model.set(hit.model)
        self._model_changed()
        self.link.set("serial")
        self._link_changed()
        self.port.set(hit.port)
        self.baud.set(str(hit.baud))
        with contextlib.suppress(Exception):
            config.save_settings({"model": hit.model, "port": hit.port, "baud": hit.baud,
                                  "tcp": None, "setup_done": True})
        if connect and not self.ctl.connected:
            self._toggle_connect()

    def _port_removed(self, info) -> None:
        self._refresh_ports()
        radio_port = getattr(getattr(self.ctl.radio, "_t", None), "port", None)
        if self.ctl.connected and radio_port == info.device:
            self._bg(self.ctl.disconnect,
                     done=lambda _r: (self.connect_btn.configure(text="Connect"),
                                      self._set_text(self.status, "")))
            self.banner.show(f"The radio on {info.device} was unplugged or switched off. "
                             "Bosun disconnected it.", kind="warn")

    def _sdr_added(self, name: str) -> None:
        if self.spectrum is None:
            return
        self.spectrum.find_sdrs()

        def show():
            self.banner.hide()
            self.spectrum.src_name.set(name)
            self.nb.select(self.spectrum)
            if self.spectrum._worker is not None:
                self.spectrum.stop()
            self.spectrum.toggle()

        self.banner.show(f"SDR plugged in: {name}.", [("Show spectrum", show)], kind="ok")

    def _sdr_removed(self, name: str) -> None:
        if self.spectrum is None:
            return
        self.spectrum.find_sdrs()
        src = self.spectrum.source
        if src is not None and getattr(src, "name", "") == name:
            self.spectrum.stop()
            self.banner.show(f"SDR {name} was unplugged; the spectrum stopped.", kind="warn")

    def detect_now(self) -> None:
        from .detect import scan_all

        if self.ctl.connected:
            self.banner.show("Disconnect first, then run Detect my radio.", kind="warn")
            return
        self.banner.show("Looking for radios on every serial port (this can take a few "
                         "seconds per port)...")

        def done(hits):
            if not hits:
                self.banner.show(
                    "No radio answered. Check the USB cable, switch the radio on, and turn "
                    "on CAT / CI-V (USB) in its menu. Radios with no PC control (e.g. "
                    "Radtel) cannot be detected.", kind="warn")
                return
            hit = hits[0]
            more = f" (and {len(hits) - 1} more)" if len(hits) > 1 else ""
            self.banner.show(
                f"Found {hit.model} on {hit.port} at {hit.baud} baud{more}.",
                [("Connect", lambda: self._use_detected(hit, connect=True)),
                 ("Just select it", lambda: self._use_detected(hit, connect=False))],
                kind="ok")

        if self.watcher is not None:
            self.watcher.paused = True

        def resume(*_):
            if self.watcher is not None:
                self.watcher.paused = False

        self._bg(scan_all, done=lambda hits: (resume(), done(hits)), fail=resume)

    # ---------- handlers ----------
    @staticmethod
    def _picker_names() -> list[str]:
        return [m for ms in registry.vendors().values() for m in ms] + sdrcat.picker_names()

    def _model_changed(self, _event=None) -> None:
        if not hasattr(self, "mode_box"):
            return
        entry = sdrcat.lookup(self.model.get())
        if entry is not None:
            self.mode_box.configure(values=sdrcat.MODES)
            if self.mode.get() not in sdrcat.MODES:
                self.mode.set("FM")
            if hasattr(self, "message"):
                self.say(f"{entry['model']}: SDR receiver. {entry['note']} Press Connect "
                         "to start it on the Spectrum tab.")
            return
        modes = modes_for(self.model.get())
        self.mode_box.configure(values=modes)
        if self.mode.get() not in modes:
            self.mode.set(modes[0] if modes else "")
        self.baud.set(str(default_baud(self.model.get())))
        if hasattr(self, "message"):
            self.say(registry.describe(self.model.get()))

    def _link_changed(self) -> None:
        if self.link.get() == "serial":
            self.tcp_row.grid_remove()
            self.serial_row.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(PAD, 0))
        else:
            self.serial_row.grid_remove()
            self.tcp_row.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(PAD, 0))

    def _refresh_ports(self) -> None:
        ports = serial_ports()
        self.port_box.configure(values=ports)
        if ports and not self.port.get():
            self.port.set(ports[0])

    def _show_status(self, st: dict) -> None:
        self._set_text(self.status, format_status(st))

    def _toggle_connect(self) -> None:
        self.connect_btn.state(["disabled"])
        if self.ctl.connected:
            def done(_r):
                self.connect_btn.configure(text="Connect")
                self.connect_btn.state(["!disabled"])
                self._set_text(self.status, "")
                self.message.set("Disconnected.")
            self._bg(self.ctl.disconnect, done=done,
                     fail=lambda _e: self.connect_btn.state(["!disabled"]))
            return

        def done(st):
            self.connect_btn.configure(text="Disconnect")
            self.connect_btn.state(["!disabled"])
            self._show_status(st)
            self.message.set(st.get("note") or f"Connected to {st.get('model')}.")

        def fail(_exc):
            self.connect_btn.state(["!disabled"])

        self.message.set("Connecting...")
        model = self.model.get()
        if sdrcat.is_sdr(model):
            self.connect_btn.state(["!disabled"])
            self.start_sdr(model)
            return
        if getattr(registry.get(model), "audio_only", False):
            self._bg(self.ctl.connect_audio_only, model, done=done, fail=fail)
        elif self.link.get() == "serial":
            self._bg(self.ctl.connect_serial, model, self.port.get(),
                     self.baud.get(), done=done, fail=fail)
        else:
            self._bg(self.ctl.connect, model, self.host.get(),
                     self.tcp_port.get(), done=done, fail=fail)

    def start_sdr(self, model: str) -> None:
        """Start an SDR receiver picked in the Radio list on the Spectrum tab."""
        entry = sdrcat.lookup(model)
        if self.spectrum is None or entry is None:
            self.say("The Spectrum tab is not available, so the SDR cannot start.")
            return
        self.message.set(f"Looking for a {entry['model']}...")

        def work():
            from .sources import RTL_TCP_DEFAULT, list_sources
            if entry["source"] == "rtl_tcp":
                return RTL_TCP_DEFAULT
            return sdrcat.match_source(entry, list_sources())

        def done(name):
            if not name:
                self.say(f"No {entry['model']} found. Plug it in (on Windows install the "
                         "WinUSB driver with Zadig once), then press Connect again.")
                return
            self.nb.select(self.spectrum)
            self.spectrum.src_name.set(name)
            freq = self.freq.get().strip()
            if freq:
                with contextlib.suppress(Exception):
                    float(freq.replace(",", "."))
                    self.spectrum.center.set(freq)
            if self.spectrum._worker is None:
                self.spectrum.toggle()
        self._bg(work, done=done)

    def tune_radio(self, hz: float) -> None:
        """Called by the spectrum view when a signal is clicked."""
        self.freq.set(f"{hz / 1e6:.6f}")
        radio = self.ctl.radio
        if radio is not None and radio.bands and not any(
                lo <= hz <= hi for lo, hi in radio.bands):
            bands = ", ".join(f"{lo / 1e6:g}-{hi / 1e6:g}" for lo, hi in radio.bands)
            self.say(f"Selected {hz / 1e6:.5f} MHz on the spectrum. The {radio.model} cannot "
                     f"tune there (it covers {bands} MHz), so only the SDR is listening.")
            return
        if self.ctl.connected and not self.ctl.audio_only:
            self._bg(self.ctl.tune, self.freq.get(), None,
                     done=lambda st: (self._show_status(st),
                                      self.say(f"Radio tuned to {hz / 1e6:.5f} MHz.")))

    def _tune(self) -> None:
        def done(st):
            self._show_status(st)
            self.message.set("Tuned.")
        self._bg(self.ctl.tune, self.freq.get(), self.mode.get(), done=done)

    def _refresh(self) -> None:
        self._bg(self.ctl.status, done=self._show_status)

    def _set_level(self, key: str) -> None:
        pct = self.levels[key].get()
        self._bg(self.ctl.set_level, key, pct,
                 done=lambda _r: self.message.set(f"{key.upper()} set to {pct:.0f}%."))

    def _toggle_scan(self) -> None:
        if self.ctl.scan is not None:
            self._bg(self.ctl.stop_scan, done=lambda _r: self._scan_stopped())
            return
        try:
            v = self.scan_vars
            self.ctl.start_scan(
                v["start"].get(), v["stop"].get(), v["step"].get(), v["dwell"].get(),
                on_step=lambda hz: self.post(self.scan_now.set, f"Scanning {hz / 1e6:.6f} MHz"),
                on_hit=lambda hz: self.post(self.hits.insert, 0, f"{hz / 1e6:.6f} MHz"),
            )
        except Exception as exc:
            self.message.set(f"Error: {exc}")
            return
        self.scan_btn.configure(text="Stop scan")
        if not self.ctl.supports_squelch():
            self.message.set("This radio cannot report squelch, so hits will not be logged.")

    def _scan_stopped(self) -> None:
        self.scan_btn.configure(text="Start scan")
        self.scan_now.set("Stopped")

    def _tune_to_hit(self, _event=None) -> None:
        sel = self.hits.curselection()
        if sel:
            self.freq.set(self.hits.get(sel[0]).split()[0])
            self._tune()

    def _probe(self) -> None:
        def work() -> str:
            from . import sdr, usb
            lines = ["Serial ports:"]
            lines += [f"  {p}" for p in serial_ports()] or ["  none"]
            lines.append("Known USB-serial bridges:")
            try:
                bridges = usb.enumerate_bridges()
                lines += [f"  {b.device}  {b.vid:04x}:{b.pid:04x}  {b.description}"
                          for b in bridges] or ["  none"]
            except Exception as exc:
                lines.append(f"  unavailable: {exc}")
            lines.append("Sound devices:")
            try:
                lines += [f"  {c}" for c in usb.list_codecs()] or ["  none"]
            except Exception as exc:
                lines.append(f"  unavailable: {exc}")
            lines.append("SDR devices:")
            try:
                found = sdr.available()
                lines += [f"  {k}: {d}" for k, devs in found.items() if k != "file"
                          for d in devs] or ["  none"]
            except Exception as exc:
                lines.append(f"  unavailable: {exc}")
            return "\n".join(lines)

        self.message.set("Scanning for devices...")
        self._bg(work, done=lambda text: (self._set_text(self.devices, text),
                                          self.message.set("Device scan done.")))

    def quit_app(self) -> None:
        try:
            self.stop_watching()
            if getattr(self, "faceplate", None) is not None:
                with contextlib.suppress(Exception):
                    self.faceplate.destroy()
            if getattr(self, "video_window", None) is not None:
                with contextlib.suppress(Exception):
                    self.video_window.close()
            for scr in list(getattr(self, "screens", [])):
                with contextlib.suppress(Exception):
                    scr.close()
            if self.spectrum is not None:
                self.spectrum.shutdown()
            self.audio_tab.shutdown()
            self.pictures.shutdown()
            self.ctl.disconnect()
        finally:
            self.root.destroy()


def _show_fatal(exc: BaseException, log) -> None:
    try:
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(
            "Bosun could not start",
            f"{type(exc).__name__}: {exc}\n\nDetails were saved to:\n{log}\n\n"
            "Please send that file to the developer.")
        r.destroy()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    from . import crashlog

    log = crashlog.setup()
    args = sys.argv[1:] if argv is None else argv
    if sys.platform.startswith("win"):
        # Sharp text on high-DPI screens, and screen captures that line up.
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
    selftest = "--selftest" in args
    try:
        root = tk.Tk()
    except Exception as exc:
        crashlog.log_exception(type(exc), exc, exc.__traceback__, "creating window")
        _show_fatal(exc, log)
        return 1

    def on_callback_error(exc_type, exc, tb):
        crashlog.log_exception(exc_type, exc, tb, "in UI callback")
        with contextlib.suppress(Exception):
            app.say(f"Something went wrong: {exc} (details in {log})")

    root.report_callback_exception = on_callback_error
    try:
        app = BosunApp(root, first_run_wizard=not selftest and "--faceplate" not in args)
    except Exception as exc:
        crashlog.log_exception(type(exc), exc, exc.__traceback__, "starting app")
        root.destroy()
        _show_fatal(exc, log)
        return 1
    crashlog.write("window ready")
    if "--faceplate" in args and not selftest:
        root.after(300, lambda: app.open_faceplate(full_screen="--full-screen" in args))
    result = {"ok": True}
    if selftest:
        # CI: run the demo spectrum, optionally click through the setup wizard
        # and probe devices, then exit; fail if anything breaks.
        if app.spectrum is not None:
            app.spectrum.src_name.set("Demo (simulated signals)")
            if "--faceplate" not in args and "--video" not in args:  # they start it
                root.after(200, app.spectrum.toggle)
            root.after(300, app.spectrum.find_sdrs)
        if "--faceplate" in args:
            def drive_faceplate():
                fp = app.open_faceplate()
                root.after(400, fp.power)
                root.after(1400, fp.toggle_night)
                root.after(2000, lambda: fp.tune(145.5e6, "FM"))
            root.after(300, drive_faceplate)
        if "--video" in args:
            def drive_video():
                vw = app.open_video()
                vw.toggle()
                from .ui.screens import ScreenWindow, monitors
                app.screens.append(ScreenWindow(app, "Video (analogue TV / FPV)",
                                                monitors(root)[0]))
            root.after(300, drive_video)
        if "--wizard" in args:
            def drive_wizard():
                from .ui.wizard import SetupWizard
                wiz = SetupWizard(root, on_done=None)
                wiz.vendor.set("Icom")
                wiz.model.set("IC-9100")
                for delay in (300, 600, 900):
                    root.after(delay, wiz.next)
                root.after(1400, wiz.destroy)
            root.after(400, drive_wizard)

        def finish():
            drawn = getattr(app.spectrum, "frames_drawn", 0) if app.spectrum else 0
            if "--video" in args:
                vw = app.video_window
                drawn = 1 if vw is not None and vw.last_frame is not None else 0
            errors = crashlog.log_path().read_text(encoding="utf-8", errors="replace")
            failed = "ERROR" in errors.split("window ready")[-1]
            result["ok"] = drawn > 0 and not failed
            print(f"selftest: spectrum frames drawn = {drawn}, errors = {failed}")
            if failed:
                print(errors.split("window ready")[-1][-3000:])
            app.quit_app()

        root.after(3500, finish)
    try:
        root.mainloop()
    except Exception as exc:
        crashlog.log_exception(type(exc), exc, exc.__traceback__, "main loop")
        _show_fatal(exc, log)
        return 1
    crashlog.write("closed normally")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
