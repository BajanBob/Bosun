"""First-run setup wizard: radio, connection / command profile, SDR, audio, test."""

from __future__ import annotations

import contextlib
import json
import threading
import tkinter as tk
from tkinter import ttk

from .. import config
from ..radios import registry
from ..radios.profile import COMMAND_KEYS, save_user_profile
from ..sources import list_sources
from ..transport import list_serial_ports
from .tips import tip

PAD = 8
NO_RADIO = "No radio (SDR only)"

PROFILE_FIELDS = [
    ("set_frequency", "Set frequency", "e.g. FRQ{hz}  or  F{mhz:.6f}"),
    ("get_frequency", "Read frequency", "e.g. FRQ?"),
    ("frequency_reply", "Frequency reply pattern", r"regex, e.g. FRQ(\d+)"),
    ("set_mode", "Set mode", "e.g. MODE {mode}"),
    ("get_mode", "Read mode", "e.g. MODE?"),
    ("mode_reply", "Mode reply pattern", r"regex, e.g. MODE (\w+)"),
    ("squelch_open", "Ask if squelch is open", "e.g. SQL?"),
    ("squelch_open_reply", "'Open' reply pattern", "regex, e.g. SQL 1"),
    ("set_af_gain", "Set volume", "e.g. VOL{val255:03d}"),
    ("set_squelch", "Set squelch", "e.g. SQ{pct}"),
]


def _ports_with_names() -> list[str]:
    try:
        from serial.tools import list_ports

        return [f"{p.device}  ({p.description})" if p.description and p.description != "n/a"
                else p.device for p in list_ports.comports()]
    except Exception:
        return list_serial_ports()


class SetupWizard(tk.Toplevel):
    STEPS = ("Your radio", "Connect", "SDR & audio", "Test & finish")

    def __init__(self, master, on_done=None) -> None:
        super().__init__(master)
        self.title("Bosun setup")
        self.transient(master)
        self.minsize(560, 460)
        self.on_done = on_done
        self.settings = config.read_settings()
        self.step = 0

        self.header = ttk.Label(self, font=("TkDefaultFont", 13, "bold"))
        self.header.pack(anchor="w", padx=PAD * 2, pady=(PAD * 2, 0))
        self.sub = ttk.Label(self, foreground="#555")
        self.sub.pack(anchor="w", padx=PAD * 2)
        self.body = ttk.Frame(self, padding=PAD * 2)
        self.body.pack(fill="both", expand=True)
        nav = ttk.Frame(self, padding=(PAD * 2, 0, PAD * 2, PAD * 2))
        nav.pack(fill="x")
        self.back_btn = ttk.Button(nav, text="< Back", command=self.back)
        self.back_btn.pack(side="left")
        self.next_btn = ttk.Button(nav, text="Next >", command=self.next)
        self.next_btn.pack(side="right")
        ttk.Button(nav, text="Cancel", command=self.destroy).pack(side="right", padx=PAD)

        # state
        vendors = registry.vendors()
        model = self.settings.get("model") or ""
        vendor = next((v for v, ms in vendors.items() if model in ms), "")
        self.vendor = tk.StringVar(value=vendor or (NO_RADIO if not model else ""))
        self.model = tk.StringVar(value=model)
        self.link = tk.StringVar(value="tcp" if self.settings.get("tcp") else "serial")
        self.port = tk.StringVar(value=self.settings.get("port") or "")
        self.baud = tk.StringVar(value=str(self.settings.get("baud") or ""))
        tcp = self.settings.get("tcp") or ""
        self.host = tk.StringVar(value=tcp.partition(":")[0])
        self.tcp_port = tk.StringVar(value=tcp.partition(":")[2])
        self.sdr = tk.StringVar(value=self.settings.get("sdr") or "")
        self.audio = tk.StringVar(value=self.settings.get("audio_input") or "")
        self.tips_on = tk.BooleanVar(value=self.settings.get("hover_tips", True))
        self.profile_vars: dict[str, tk.StringVar] = {}
        self.result = tk.StringVar(value="")
        self._show()
        self.grab_set()

    # ---------------------------------------------------------------- nav
    def _clear(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

    def _show(self) -> None:
        self._clear()
        self.header.configure(text=f"Step {self.step + 1} of {len(self.STEPS)}: "
                                   f"{self.STEPS[self.step]}")
        getattr(self, f"_step{self.step}")()
        self.back_btn.state(["!disabled"] if self.step else ["disabled"])
        self.next_btn.configure(text="Finish" if self.step == len(self.STEPS) - 1
                                else "Next >")

    def back(self) -> None:
        if self.step:
            self.step -= 1
            self._show()

    def next(self) -> None:
        if self.step == 0 and self.vendor.get() != NO_RADIO and not self.model.get():
            self.sub.configure(text="Choose a model, or 'No radio (SDR only)'.")
            return
        if self.step == 1:
            self._save_profile_if_editing()
        if self.step == len(self.STEPS) - 1:
            self.finish()
            return
        self.step += 1
        self._show()

    # ---------------------------------------------------------------- steps
    def _radio_cls(self):
        try:
            return registry.get(self.model.get())
        except Exception:
            return None

    def _step0(self) -> None:
        self.sub.configure(text="Choose the maker, then the model. Bosun fills in the "
                                "usual settings for you.")
        vendors = registry.vendors()
        left = ttk.Frame(self.body)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Maker").pack(anchor="w")
        vlist = tk.Listbox(left, height=12, exportselection=False, width=18)
        for v in [*vendors, NO_RADIO]:
            vlist.insert("end", v)
        vlist.pack(fill="y", expand=True)
        right = ttk.Frame(self.body, padding=(PAD * 2, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Model").pack(anchor="w")
        mlist = tk.Listbox(right, height=8, exportselection=False)
        mlist.pack(fill="x")
        info = ttk.Label(right, wraplength=320, justify="left")
        info.pack(anchor="w", pady=PAD)

        def show_models(_e=None):
            sel = vlist.curselection()
            if not sel:
                return
            vendor = vlist.get(sel[0])
            self.vendor.set(vendor)
            mlist.delete(0, "end")
            if vendor == NO_RADIO:
                self.model.set("")
                info.configure(text="Use Bosun with an RTL-SDR or other SDR only: live "
                                    "spectrum, automatic detection, recording. You can add "
                                    "a radio later.")
                return
            for m in vendors[vendor]:
                mlist.insert("end", m)
            if self.model.get() in vendors[vendor]:
                i = vendors[vendor].index(self.model.get())
                mlist.selection_set(i)
                show_info()

        def show_info(_e=None):
            sel = mlist.curselection()
            if sel:
                self.model.set(mlist.get(sel[0]))
                info.configure(text=registry.describe(self.model.get()))

        vlist.bind("<<ListboxSelect>>", show_models)
        mlist.bind("<<ListboxSelect>>", show_info)
        names = [*vendors, NO_RADIO]
        if self.vendor.get() in names:
            vlist.selection_set(names.index(self.vendor.get()))
            show_models()

    def _step1(self) -> None:
        cls = self._radio_cls()
        if cls is None:
            self.sub.configure(text="No radio selected: nothing to connect. Press Next.")
            return
        if getattr(cls, "audio_only", False):
            self.sub.configure(text=f"{cls.model} has no computer control.")
            ttk.Label(self.body, wraplength=500, justify="left", text=(
                "Connect the radio's speaker or headphone output to your computer's line-in "
                "(or a USB sound adapter). On the next step choose that input. Bosun can then "
                "record what the radio hears, and export frequencies it finds as a CHIRP / "
                "Radtel CPS channel list.\n\nProgram the radio itself with Radtel's "
                "programming software (or CHIRP once it supports this model).")).pack(
                anchor="w")
            return
        self.sub.configure(text="How is the radio connected to this computer?")
        if getattr(cls, "needs_setup", False):
            self._profile_editor(cls)
        if not self.baud.get():
            self.baud.set(str(cls.default_baud))
        box = ttk.Frame(self.body)
        box.pack(fill="x", pady=(PAD, 0))
        box.columnconfigure(1, weight=1)
        tip(ttk.Radiobutton(box, text="USB / serial cable", value="serial",
                            variable=self.link), "link_serial").grid(row=0, column=0,
                                                                      sticky="w")
        tip(ttk.Radiobutton(box, text="Network (TCP)", value="tcp", variable=self.link),
            "link_tcp").grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="Port").grid(row=1, column=0, sticky="w", pady=4)
        ports = _ports_with_names()
        pb = tip(ttk.Combobox(box, textvariable=self.port, values=ports), "port")
        pb.grid(row=1, column=1, sticky="ew", padx=PAD)
        if ports and not self.port.get():
            self.port.set(ports[0])
        ttk.Label(box, text="Baud").grid(row=2, column=0, sticky="w")
        tip(ttk.Entry(box, textvariable=self.baud, width=10), "baud").grid(
            row=2, column=1, sticky="w", padx=PAD)
        ttk.Label(box, text="Host / IP").grid(row=3, column=0, sticky="w", pady=4)
        tip(ttk.Entry(box, textvariable=self.host), "host").grid(row=3, column=1,
                                                                  sticky="ew", padx=PAD)
        ttk.Label(box, text="TCP port").grid(row=4, column=0, sticky="w")
        tip(ttk.Entry(box, textvariable=self.tcp_port, width=10), "tcp_port").grid(
            row=4, column=1, sticky="w", padx=PAD)
        if not ports:
            ttk.Label(box, foreground="#a60", wraplength=480, text=(
                "No serial ports found. Plug in the radio's USB cable, install its USB "
                "driver (Silicon Labs CP210x, FTDI or the maker's), then go Back and Next "
                "to look again.")).grid(row=5, column=0, columnspan=2, sticky="w", pady=PAD)

    def _profile_editor(self, cls) -> None:
        prof = dict(cls.profile)
        cmds = prof.get("commands", {})
        frame = ttk.LabelFrame(self.body, text=f"{cls.model} command profile", padding=PAD)
        frame.pack(fill="x")
        ttk.Label(frame, wraplength=500, justify="left", foreground="#555", text=(
            "This radio's commands are only in its remote-control manual, so Bosun asks "
            "you to copy them in once. Leave unknown ones blank. Use {hz}, {khz}, {mhz}, "
            "{mode}, {pct} or {val255} where the value goes.")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        frame.columnconfigure(1, weight=1)
        for r, (key, label, example) in enumerate(PROFILE_FIELDS, start=1):
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky="w")
            var = tk.StringVar(value=cmds.get(key, ""))
            e = ttk.Entry(frame, textvariable=var)
            e.grid(row=r, column=1, sticky="ew", padx=PAD, pady=1)
            from .tips import Tooltip
            Tooltip(e, f"{label}. {example}")
            self.profile_vars[key] = var
        self.term = tk.StringVar(value=prof.get("terminator", "\\r"))
        ttk.Label(frame, text="Line ending").grid(row=99, column=0, sticky="w")
        t = ttk.Combobox(frame, textvariable=self.term, values=["\\r", "\\n", "\\r\\n", ";"],
                         width=6)
        t.grid(row=99, column=1, sticky="w", padx=PAD)
        self._editing = cls

    def _save_profile_if_editing(self) -> None:
        cls = getattr(self, "_editing", None)
        if cls is None or not self.profile_vars:
            return
        prof = json.loads(json.dumps(cls.profile))
        prof.setdefault("commands", {})
        for key, var in self.profile_vars.items():
            prof["commands"][key] = var.get().strip()
        prof["terminator"] = self.term.get() or "\\r"
        with contextlib.suppress(ValueError):
            prof["baud"] = int(self.baud.get())
        save_user_profile(prof)
        registry.reload()
        self._editing = None
        self.profile_vars = {}

    def _step2(self) -> None:
        self.sub.configure(text="Optional: an SDR for the live spectrum, and the sound "
                                "input carrying your radio's audio.")
        box = ttk.Frame(self.body)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Spectrum source").grid(row=0, column=0, sticky="w")
        sources = list_sources()
        tip(ttk.Combobox(box, textvariable=self.sdr, values=sources, state="readonly"),
            "source").grid(row=0, column=1, sticky="ew", padx=PAD, pady=4)
        if not self.sdr.get():
            self.sdr.set(sources[-1] if len(sources) > 1 else sources[0])
        ttk.Label(box, foreground="#555", wraplength=480, justify="left", text=(
            "RTL-SDR dongles work out of the box on Windows once the WinUSB driver is "
            "installed with Zadig; on Linux, unplug and replug after installing. Other "
            "SDRs work through SoapySDR. 'Demo' simulates a busy band.")).grid(
            row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(box, text="Radio audio input").grid(row=2, column=0, sticky="w", pady=4)
        try:
            from ..recorder import input_devices
            inputs = input_devices()
        except Exception as exc:
            inputs = []
            ttk.Label(box, foreground="#a60", text=f"Audio unavailable: {exc}").grid(
                row=3, column=0, columnspan=2, sticky="w")
        tip(ttk.Combobox(box, textvariable=self.audio, values=inputs), "audio_in").grid(
            row=2, column=1, sticky="ew", padx=PAD)
        tip(ttk.Checkbutton(box, text="Show helpful tips when hovering over controls",
                            variable=self.tips_on), "Turn hover tips on or off.").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=PAD)

    def _step3(self) -> None:
        cls = self._radio_cls()
        self.sub.configure(text="Check the connection, then press Finish to save.")
        summary = [f"Radio: {cls.model if cls else 'none (SDR only)'}"]
        if cls and not getattr(cls, "audio_only", False):
            summary.append("Link: " + (f"{self.port.get().split()[0] if self.port.get() else '?'}"
                                       f" at {self.baud.get()} baud" if self.link.get() == "serial"
                                       else f"{self.host.get()}:{self.tcp_port.get()}"))
        summary.append(f"Spectrum: {self.sdr.get() or 'none'}")
        summary.append(f"Audio input: {self.audio.get() or 'none'}")
        ttk.Label(self.body, text="\n".join(summary), justify="left").pack(anchor="w")
        if cls and not getattr(cls, "audio_only", False):
            tip(ttk.Button(self.body, text="Test connection", command=self.test),
                "connect").pack(anchor="w", pady=PAD)
        ttk.Label(self.body, textvariable=self.result, wraplength=500,
                  justify="left").pack(anchor="w")

    # ---------------------------------------------------------------- actions
    def _endpoint(self) -> dict:
        port = self.port.get().split()[0] if self.port.get() else ""
        if self.link.get() == "serial":
            return {"port": port or None, "tcp": None,
                    "baud": int(self.baud.get()) if self.baud.get().isdigit() else None}
        return {"tcp": f"{self.host.get().strip()}:{self.tcp_port.get().strip()}",
                "port": None, "baud": None}

    def test(self) -> None:
        from ..control import Controller

        self.result.set("Testing...")
        ep, model = self._endpoint(), self.model.get()

        def work():
            ctl = Controller()
            try:
                if ep.get("tcp"):
                    host, _, port = ep["tcp"].partition(":")
                    st = ctl.connect(model, host, port)
                else:
                    st = ctl.connect_serial(model, ep.get("port") or "", ep.get("baud"))
                freq = st.get("frequency")
                ok = isinstance(freq, float)
                msg = (f"Success: the radio answered, {freq / 1e6:.6f} MHz {st.get('mode')}."
                       if ok else f"The port opened but the radio did not answer ({freq}). "
                       "Check the baud rate and that CAT / CI-V is enabled in the radio's "
                       "menu.")
            except Exception as exc:
                msg = f"Could not connect: {exc}"
            finally:
                ctl.disconnect()
            box.append(msg)

        box: list[str] = []

        def poll():
            if box:
                self.result.set(box[0])
            elif self.winfo_exists():
                self.after(100, poll)

        threading.Thread(target=work, daemon=True).start()
        self.after(100, poll)

    def finish(self) -> None:
        updates = {"model": self.model.get() or None, "sdr": self.sdr.get() or None,
                   "audio_input": self.audio.get() or None,
                   "hover_tips": bool(self.tips_on.get()), "setup_done": True}
        cls = self._radio_cls()
        if cls is not None and not getattr(cls, "audio_only", False):
            updates.update(self._endpoint())
        else:
            updates.update({"port": None, "tcp": None, "baud": None})
        path = config.save_settings(updates)
        if self.on_done:
            self.on_done(updates, path)
        self.destroy()


__all__ = ["SetupWizard", "COMMAND_KEYS"]
