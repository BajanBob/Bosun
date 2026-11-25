"""UI-independent logic shared by the desktop and mobile apps.

All calls block; the apps run them off the UI thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from bosun.caps import Cap
from bosun.errors import BosunError
from bosun.radios.registry import DRIVERS, catalogue
from bosun.scan import ScanEngine
from bosun.transport import SerialTransport, TCPTransport, list_serial_ports


def serial_ports() -> list[str]:
    return list_serial_ports()


def default_baud(model: str) -> int:
    return DRIVERS[model].default_baud


def models() -> list[str]:
    return sorted(DRIVERS)


def modes_for(model: str) -> list[str]:
    return list(DRIVERS[model].modes)


def describe_catalogue() -> str:
    lines = []
    for e in catalogue():
        bands = ", ".join(f"{lo:g}-{hi:g}" for lo, hi in e["bands_mhz"])
        lines.append(f"{e['model']} ({e['vendor']})\n  Bands MHz: {bands}\n"
                     f"  Modes: {' '.join(e['modes'])}")
    from .sdr.catalogue import catalogue as sdr_catalogue

    lines.append("SDR RECEIVERS (receive only; use them on the Spectrum / SDR tab)")
    for e in sdr_catalogue():
        bands = ", ".join(f"{lo:g}-{hi:g}" for lo, hi in e["bands_mhz"])
        lines.append(f"{e['model']} ({e['vendor']})\n  Bands MHz: {bands}\n"
                     f"  Modes: {' '.join(e['modes'])}\n  {e['note']}")
    return "\n\n".join(lines)


def parse_endpoint(host: str, port: str) -> tuple[str, int]:
    host = (host or "").strip()
    if not host:
        raise BosunError("enter the host or IP address of your serial-over-network adapter")
    try:
        num = int(str(port).strip())
    except ValueError:
        raise BosunError("port must be a number") from None
    if not 1 <= num <= 65535:
        raise BosunError("port must be between 1 and 65535")
    return host, num


def parse_mhz(text: str, label: str = "frequency") -> float:
    try:
        value = float(str(text).strip().replace(",", "."))
    except ValueError:
        raise BosunError(f"{label} must be a number in MHz") from None
    if value <= 0:
        raise BosunError(f"{label} must be above zero")
    return value * 1e6


class Controller:
    """Holds one radio connection and an optional scan."""

    def __init__(self, transport_factory=TCPTransport, serial_factory=SerialTransport) -> None:
        self._factory = transport_factory
        self._serial_factory = serial_factory
        self.radio = None
        self.scan: ScanEngine | None = None
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self.radio is not None

    def connect(self, model: str, host: str, port: str) -> dict:
        if model not in DRIVERS:
            raise BosunError(f"unknown model {model!r}")
        h, p = parse_endpoint(host, port)
        return self._open(model, self._factory(h, p))

    def connect_serial(self, model: str, port: str, baud: str | int | None = None) -> dict:
        if model not in DRIVERS:
            raise BosunError(f"unknown model {model!r}")
        port = (port or "").strip()
        if not port:
            raise BosunError("choose a serial port (e.g. COM3 or /dev/ttyUSB0)")
        if baud in (None, ""):
            rate = DRIVERS[model].default_baud
        else:
            try:
                rate = int(str(baud).strip())
            except ValueError:
                raise BosunError("baud rate must be a number") from None
        return self._open(model, self._serial_factory(port, rate))

    def connect_audio_only(self, model: str) -> dict:
        """Radios with no PC control (e.g. Radtel RT-950 Pro)."""
        return self._open(model, None)

    def _open(self, model: str, transport) -> dict:
        self.disconnect()
        cls = DRIVERS[model]
        radio = cls(transport) if transport is not None else cls()
        radio.connect()
        self.radio = radio
        return self.status()

    def set_level(self, name: str, pct: float) -> None:
        """name: af, rf or squelch; pct 0-100."""
        radio = self._need()
        fn = {"af": "set_af_gain", "rf": "set_rf_gain", "squelch": "set_squelch"}[name]
        if not hasattr(radio, fn):
            raise BosunError(f"{radio.model} has no {name} control")
        with self._lock:
            getattr(radio, fn)(float(pct))

    def disconnect(self) -> None:
        self.stop_scan()
        if self.radio is not None:
            try:
                self.radio.disconnect()
            finally:
                self.radio = None

    def _need(self):
        if self.radio is None:
            raise BosunError("not connected")
        return self.radio

    def status(self) -> dict:
        with self._lock:
            return self._need().status()

    @property
    def audio_only(self) -> bool:
        return bool(getattr(self.radio, "audio_only", False))

    def tune(self, mhz: str, mode: str | None) -> dict:
        radio = self._need()
        if self.audio_only:
            raise BosunError(f"{radio.model} has no computer control; tune it on the radio")
        hz = parse_mhz(mhz)
        with self._lock:
            radio.set_frequency(hz)
            if mode:
                radio.set_mode(mode)
        return self.status()

    def supports_squelch(self) -> bool:
        return self.radio is not None and self.radio.caps.has(Cap.SQUELCH)

    def start_scan(self, start: str, stop: str, step_khz: str, dwell: str,
                   on_step: Callable[[float], None] | None = None,
                   on_hit: Callable[[float], None] | None = None) -> ScanEngine:
        radio = self._need()
        self.stop_scan()
        try:
            step_hz = float(str(step_khz).strip()) * 1e3
            dwell_s = float(str(dwell).strip())
        except ValueError:
            raise BosunError("step (kHz) and dwell (s) must be numbers") from None
        detector = radio.squelch_open if self.supports_squelch() else None
        engine = ScanEngine(radio, mode="range", dwell=dwell_s, detector=detector,
                            on_step=on_step, on_hit=on_hit)
        engine.use_range(parse_mhz(start, "start"), parse_mhz(stop, "stop"), step_hz)
        engine.start()
        self.scan = engine
        return engine

    def stop_scan(self) -> None:
        if self.scan is not None:
            self.scan.stop()
            self.scan.join(2.0)
            self.scan = None


def format_status(st: dict) -> str:
    freq = st.get("frequency")
    if isinstance(freq, (int, float)):
        freq = f"{freq / 1e6:.6f} MHz"
    text = (f"{st.get('model')} ({st.get('vendor')})\n"
            f"Connected: {'yes' if st.get('connected') else 'no'}\n"
            f"Frequency: {freq}\nMode: {st.get('mode')}")
    if st.get("note"):
        text += f"\n{st['note']}"
    return text
