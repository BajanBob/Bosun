"""Bosun desktop app (Tkinter). Runs radio I/O on worker threads."""

from __future__ import annotations

import pathlib
import queue
import threading
import tkinter as tk
from tkinter import ttk

from .control import (
    Controller,
    default_baud,
    describe_catalogue,
    format_status,
    models,
    modes_for,
    serial_ports,
)
from .version import __version__

PAD = 6
ICON = pathlib.Path(__file__).with_name("assets") / "bosun.png"


class BosunApp(ttk.Frame):
    def __init__(self, root: tk.Tk, controller: Controller | None = None) -> None:
        super().__init__(root, padding=PAD * 2)
        self.root = root
        self.ctl = controller or Controller()
        self._results: queue.Queue = queue.Queue()
        root.title(f"Bosun {__version__}")
        root.minsize(620, 520)
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
        self.rowconfigure(1, weight=1)

        self._build_connection()
        nb = ttk.Notebook(self)
        nb.grid(row=1, column=0, sticky="nsew", pady=(PAD, 0))
        nb.add(self._build_control(nb), text="Control")
        nb.add(self._build_scan(nb), text="Scan")
        nb.add(self._build_devices(nb), text="Devices")
        nb.add(self._build_catalogue(nb), text="Radios")
        self.message = tk.StringVar(value="Not connected.")
        ttk.Label(self, textvariable=self.message, anchor="w").grid(
            row=2, column=0, sticky="ew", pady=(PAD, 0))
        self._refresh_ports()
        self.after(50, self._drain)

    # ---------- layout ----------
    def _build_connection(self) -> None:
        box = ttk.LabelFrame(self, text="Connection", padding=PAD)
        box.grid(row=0, column=0, sticky="ew")
        for c in (1, 3):
            box.columnconfigure(c, weight=1)

        ttk.Label(box, text="Radio").grid(row=0, column=0, sticky="w")
        self.model = tk.StringVar(value=models()[0])
        cb = ttk.Combobox(box, textvariable=self.model, values=models(), state="readonly")
        cb.grid(row=0, column=1, sticky="ew", padx=PAD)
        cb.bind("<<ComboboxSelected>>", self._model_changed)

        self.link = tk.StringVar(value="serial")
        links = ttk.Frame(box)
        links.grid(row=0, column=2, columnspan=2, sticky="w")
        ttk.Radiobutton(links, text="USB / serial", value="serial", variable=self.link,
                        command=self._link_changed).pack(side="left")
        ttk.Radiobutton(links, text="Network (TCP)", value="tcp", variable=self.link,
                        command=self._link_changed).pack(side="left", padx=PAD)

        self.serial_row = ttk.Frame(box)
        self.serial_row.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(PAD, 0))
        self.serial_row.columnconfigure(1, weight=1)
        ttk.Label(self.serial_row, text="Port").grid(row=0, column=0, sticky="w")
        self.port = tk.StringVar()
        self.port_box = ttk.Combobox(self.serial_row, textvariable=self.port)
        self.port_box.grid(row=0, column=1, sticky="ew", padx=PAD)
        ttk.Button(self.serial_row, text="Refresh", command=self._refresh_ports).grid(
            row=0, column=2)
        ttk.Label(self.serial_row, text="Baud").grid(row=0, column=3, padx=(PAD * 2, 0))
        self.baud = tk.StringVar(value=str(default_baud(self.model.get())))
        ttk.Entry(self.serial_row, textvariable=self.baud, width=8).grid(
            row=0, column=4, padx=PAD)

        self.tcp_row = ttk.Frame(box)
        self.tcp_row.columnconfigure(1, weight=1)
        ttk.Label(self.tcp_row, text="Host / IP").grid(row=0, column=0, sticky="w")
        self.host = tk.StringVar()
        ttk.Entry(self.tcp_row, textvariable=self.host).grid(
            row=0, column=1, sticky="ew", padx=PAD)
        ttk.Label(self.tcp_row, text="TCP port").grid(row=0, column=2)
        self.tcp_port = tk.StringVar()
        ttk.Entry(self.tcp_row, textvariable=self.tcp_port, width=8).grid(
            row=0, column=3, padx=PAD)

        self.connect_btn = ttk.Button(box, text="Connect", command=self._toggle_connect)
        self.connect_btn.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(PAD, 0))

    def _build_control(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Frequency (MHz)").grid(row=0, column=0, sticky="w")
        self.freq = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.freq)
        e.grid(row=0, column=1, sticky="ew", padx=PAD)
        e.bind("<Return>", lambda _e: self._tune())
        ttk.Label(f, text="Mode").grid(row=0, column=2)
        self.mode = tk.StringVar()
        self.mode_box = ttk.Combobox(f, textvariable=self.mode, state="readonly", width=8)
        self.mode_box.grid(row=0, column=3, padx=PAD)
        self._model_changed()
        ttk.Button(f, text="Tune", command=self._tune).grid(row=0, column=4)

        levels = ttk.LabelFrame(f, text="Levels (%)", padding=PAD)
        levels.grid(row=1, column=0, columnspan=5, sticky="ew", pady=PAD)
        levels.columnconfigure(1, weight=1)
        self.levels = {}
        for i, (key, text) in enumerate((("af", "AF gain"), ("rf", "RF gain"),
                                         ("squelch", "Squelch"))):
            ttk.Label(levels, text=text).grid(row=i, column=0, sticky="w")
            var = tk.DoubleVar(value=50)
            s = ttk.Scale(levels, from_=0, to=100, variable=var)
            s.grid(row=i, column=1, sticky="ew", padx=PAD)
            s.bind("<ButtonRelease-1>", lambda _e, k=key: self._set_level(k))
            val = ttk.Label(levels, width=4)
            val.grid(row=i, column=2)
            var.trace_add("write", lambda *_a, v=var, lab=val: lab.configure(
                text=f"{v.get():.0f}"))
            var.set(50)
            self.levels[key] = var

        ttk.Button(f, text="Read status", command=self._refresh).grid(
            row=2, column=0, sticky="w")
        self.status = tk.Text(f, height=6, state="disabled", wrap="word")
        self.status.grid(row=3, column=0, columnspan=5, sticky="nsew", pady=(PAD, 0))
        f.rowconfigure(3, weight=1)
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
            ttk.Entry(f, textvariable=var).grid(row=r, column=c * 2 + 1, sticky="ew",
                                                padx=PAD)
            self.scan_vars[key] = var
        self.scan_btn = ttk.Button(f, text="Start scan", command=self._toggle_scan)
        self.scan_btn.grid(row=2, column=0, columnspan=4, sticky="ew", pady=PAD)
        self.scan_now = tk.StringVar(value="Idle")
        ttk.Label(f, textvariable=self.scan_now).grid(row=3, column=0, columnspan=4,
                                                      sticky="w")
        self.hits = tk.Listbox(f, height=10)
        self.hits.grid(row=4, column=0, columnspan=4, sticky="nsew", pady=(PAD, 0))
        self.hits.bind("<Double-Button-1>", self._tune_to_hit)
        ttk.Label(f, text="Hits are logged when the radio reports open squelch. "
                          "Double-click a hit to tune to it.").grid(
            row=5, column=0, columnspan=4, sticky="w")
        f.rowconfigure(4, weight=1)
        return f

    def _build_devices(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        ttk.Button(f, text="Scan for devices", command=self._probe).pack(anchor="w")
        self.devices = tk.Text(f, height=12, state="disabled")
        self.devices.pack(fill="both", expand=True, pady=(PAD, 0))
        return f

    def _build_catalogue(self, parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=PAD)
        t = tk.Text(f, wrap="word")
        t.insert("1.0", describe_catalogue())
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)
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

    def _post(self, fn, *args) -> None:
        self._results.put((lambda _r: fn(*args), None, None, None))

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    # ---------- handlers ----------
    def _model_changed(self, _event=None) -> None:
        modes = modes_for(self.model.get())
        self.mode_box.configure(values=modes)
        if self.mode.get() not in modes:
            self.mode.set(modes[0] if modes else "")
        if hasattr(self, "baud"):
            self.baud.set(str(default_baud(self.model.get())))

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
            self.message.set(f"Connected to {st.get('model')}.")

        def fail(_exc):
            self.connect_btn.state(["!disabled"])

        self.message.set("Connecting...")
        if self.link.get() == "serial":
            self._bg(self.ctl.connect_serial, self.model.get(), self.port.get(),
                     self.baud.get(), done=done, fail=fail)
        else:
            self._bg(self.ctl.connect, self.model.get(), self.host.get(),
                     self.tcp_port.get(), done=done, fail=fail)

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
                on_step=lambda hz: self._post(self.scan_now.set, f"Scanning {hz / 1e6:.6f} MHz"),
                on_hit=lambda hz: self._post(self.hits.insert, 0, f"{hz / 1e6:.6f} MHz"),
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
            lines.append("USB audio codecs:")
            try:
                lines += [f"  {c}" for c in usb.list_codecs()] or ["  none"]
            except Exception as exc:
                lines.append(f"  unavailable: {exc}")
            lines.append("SDR devices:")
            try:
                found = sdr.available()
                lines += [f"  {k}: {d}" for k, devs in found.items() for d in devs] or ["  none"]
            except Exception as exc:
                lines.append(f"  unavailable: {exc}")
            return "\n".join(lines)

        self.message.set("Scanning for devices...")
        self._bg(work, done=lambda text: (self._set_text(self.devices, text),
                                          self.message.set("Device scan done.")))

    def quit_app(self) -> None:
        try:
            self.ctl.disconnect()
        finally:
            self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    app = BosunApp(root)
    if "--selftest" in args:
        # Build the window, let it draw, then exit cleanly. Used by CI.
        root.after(1500, app.quit_app)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
