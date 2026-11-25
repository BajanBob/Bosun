"""Automatic detection of plugged-in radios and SDRs.

- `port_info()` lists serial ports with their USB details.
- `identify()` asks a port "who are you?" using each maker's identify command
  at the usual speeds: Yaesu / Kenwood "ID;", Icom CI-V frequency read at
  each known address. Unknown Yaesu / Kenwood IDs fall back to that maker's
  common command set.
- `DeviceWatcher` polls in the background and reports devices that appear or
  disappear.
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .errors import BosunError
from .radios.protocols import CivCodec

# USB vendor:product IDs worth naming.
USB_NAMES = {
    (0x10C4, 0xEA60): "Silicon Labs CP210x (Icom, Yaesu, Kenwood, AOR)",
    (0x10C4, 0xEA70): "Silicon Labs CP2105 dual port (Yaesu, Icom)",
    (0x10C4, 0xEA71): "Silicon Labs CP2108",
    (0x0403, 0x6001): "FTDI FT232 (CAT / CI-V cable)",
    (0x0403, 0x6015): "FTDI FT-X (CAT / CI-V cable)",
    (0x0403, 0x6010): "FTDI FT2232",
    (0x067B, 0x2303): "Prolific PL2303 (programming cable)",
    (0x1A86, 0x7523): "CH340 (programming cable, e.g. Radtel / Baofeng)",
    (0x1A86, 0x55D4): "CH9102 (programming cable)",
}
PROGRAMMING_CABLES = {(0x067B, 0x2303), (0x1A86, 0x7523), (0x1A86, 0x55D4)}

YAESU_IDS = {"0670": "FT-991A", "0800": "FT-710", "0761": "FTDX10", "0681": "FTDX101D",
             "0650": "FT-891"}
KENWOOD_IDS = {"019": "TS-2000", "020": "TS-480", "021": "TS-590SG", "023": "TS-590SG",
               "024": "TS-890S"}
CAT_BAUDS = (38400, 115200, 9600, 19200, 4800, 57600)
CIV_BAUDS = (19200, 115200, 9600)


@dataclass
class PortInfo:
    device: str
    vid: int | None = None
    pid: int | None = None
    description: str = ""
    manufacturer: str = ""
    product: str = ""
    serial: str = ""

    @property
    def usb_name(self) -> str:
        return USB_NAMES.get((self.vid, self.pid), "") if self.vid is not None else ""

    @property
    def text(self) -> str:
        return " ".join([self.description, self.manufacturer, self.product,
                         self.serial]).lower()

    @property
    def is_programming_cable(self) -> bool:
        return (self.vid, self.pid) in PROGRAMMING_CABLES

    def label(self) -> str:
        bits = [self.device]
        name = self.usb_name or self.description
        if name and name.lower() != "n/a":
            bits.append(f"({name})")
        return " ".join(bits)

    def maker_hint(self) -> str | None:
        t = self.text
        if "icom" in t or re.search(r"\bic-?[r0-9]", t):
            return "Icom"
        if "yaesu" in t or re.search(r"\bft-?(dx)?\d", t):
            return "Yaesu"
        if "kenwood" in t or re.search(r"\bts-?\d", t):
            return "Kenwood"
        return None


@dataclass
class Identified:
    model: str
    port: str
    baud: int
    detail: str = ""


def port_info() -> dict[str, PortInfo]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return {}
    out = {}
    for p in list_ports.comports():
        out[p.device] = PortInfo(p.device, p.vid, p.pid, p.description or "",
                                 p.manufacturer or "", p.product or "",
                                 p.serial_number or "")
    return out


def _serial_factory(port: str, baud: int):
    from .transport import SerialTransport

    return SerialTransport(port, baud, settle=0.05)


def _ask_cat(transport, timeout: float) -> str | None:
    transport.flush_input()
    transport.write(b"ID;")
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        buf += transport.read(64, 0.05)
        m = re.search(rb"ID(\d{3,4});", buf)
        if m:
            return m.group(1).decode()
    return None


def _ask_civ(transport, addr: int, timeout: float) -> bool:
    codec = CivCodec(addr)
    transport.flush_input()
    transport.write(codec.frame(b"\x03"))
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        buf += transport.read(64, 0.05)
        frames, _ = codec.split(buf)
        if any(f[:1] == b"\x03" and len(f) >= 6 for f in frames):
            return True
    return False


def icom_addresses() -> dict[int, str]:
    """CI-V address -> model, from the built-in Icom drivers."""
    from .radios.registry import DRIVERS
    from .transport import NullTransport

    out = {}
    for cls in DRIVERS.values():
        if getattr(cls, "vendor", "") == "Icom":
            try:
                out[cls(NullTransport()).addr] = cls.model
            except Exception:
                continue
    return out


def identify(port: str, *, hint: str | None = None, factory=_serial_factory,
             timeout: float = 0.35, stop: Callable[[], bool] | None = None
             ) -> Identified | None:
    """Try to recognise the radio on `port`. Returns None if nothing answered."""
    order = ["Yaesu/Kenwood", "Icom"]
    if hint == "Icom":
        order.reverse()
    for family in order:
        bauds = CAT_BAUDS if family != "Icom" else CIV_BAUDS
        for baud in bauds:
            if stop and stop():
                return None
            try:
                t = factory(port, baud)
                t.open()
            except Exception as exc:
                raise BosunError(f"cannot open {port}: {exc}") from exc
            try:
                if family == "Icom":
                    for addr, model in icom_addresses().items():
                        if _ask_civ(t, addr, timeout):
                            return Identified(model, port, baud, f"CI-V address 0x{addr:02X}")
                    continue
                rid = _ask_cat(t, timeout)
                if rid is None:
                    continue
                if len(rid) == 4:
                    model = YAESU_IDS.get(rid, "FT-991A")
                    note = "" if rid in YAESU_IDS else " (unlisted Yaesu: using the common command set)"
                    return Identified(model, port, baud, f"Yaesu ID {rid}{note}")
                model = KENWOOD_IDS.get(rid, "TS-590SG")
                note = "" if rid in KENWOOD_IDS else " (unlisted Kenwood: using the common command set)"
                return Identified(model, port, baud, f"Kenwood ID {rid}{note}")
            finally:
                with contextlib.suppress(Exception):
                    t.close()
    return None


def scan_all(factory=_serial_factory, stop=None) -> list[Identified]:
    found = []
    for dev, info in port_info().items():
        if info.is_programming_cable:
            continue
        try:
            hit = identify(dev, hint=info.maker_hint(), factory=factory, stop=stop)
        except BosunError:
            continue
        if hit:
            found.append(hit)
    return found


def sdr_devices() -> list[str]:
    try:
        from .sdr import available

        return [d if d.startswith(f"{k}:") else f"{k}:{d}"
                for k, devs in available().items() if k != "file" for d in devs]
    except Exception:
        return []


class DeviceWatcher:
    """Polls serial ports (fast) and SDRs (slower); calls back on changes.

    Callbacks run on the watcher thread: hand them to the UI thread yourself.
    """

    def __init__(self, on_port_added=None, on_port_removed=None, on_sdr_added=None,
                 on_sdr_removed=None, port_interval: float = 1.5,
                 sdr_interval: float = 4.0) -> None:
        self.on_port_added, self.on_port_removed = on_port_added, on_port_removed
        self.on_sdr_added, self.on_sdr_removed = on_sdr_added, on_sdr_removed
        self.port_interval, self.sdr_interval = port_interval, sdr_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.ports: dict[str, PortInfo] = {}
        self.sdrs: list[str] = []
        self.paused = False

    def start(self) -> None:
        # Take a baseline so devices already present are not announced.
        self.ports = port_info()
        self.sdrs = sdr_devices()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="bosun-watch")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        next_sdr = time.monotonic() + self.sdr_interval
        while not self._stop.wait(self.port_interval):
            if self.paused:
                continue
            now = port_info()
            for dev in now.keys() - self.ports.keys():
                if self.on_port_added:
                    self.on_port_added(now[dev])
            for dev in self.ports.keys() - now.keys():
                if self.on_port_removed:
                    self.on_port_removed(self.ports[dev])
            self.ports = now
            if time.monotonic() >= next_sdr:
                next_sdr = time.monotonic() + self.sdr_interval
                sdrs = sdr_devices()
                for name in set(sdrs) - set(self.sdrs):
                    if self.on_sdr_added:
                        self.on_sdr_added(name)
                for name in set(self.sdrs) - set(sdrs):
                    if self.on_sdr_removed:
                        self.on_sdr_removed(name)
                self.sdrs = sdrs
