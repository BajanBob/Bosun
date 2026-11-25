"""Driver base: capability gating, framing, request/reply."""

from __future__ import annotations

import threading

from ..caps import Cap
from ..errors import OutOfRange, ProtocolError, UnsupportedCapability
from ..memory import Memory
from .protocols import Codec


class RadioBase:
    model = "abstract"
    vendor = "abstract"
    caps = Cap.NONE
    transport_kind = "serial"
    default_baud = 9600
    audio_format = (48000, 1, "int16")
    bridge_ids: list[tuple[int, int]] = []
    bands: list[tuple[float, float]] = []
    modes: dict[str, object] = {}
    max_channel = 99

    def __init__(self, transport, codec: Codec, *, reply_timeout: float = 0.4) -> None:
        self._t, self._codec, self._timeout = transport, codec, reply_timeout
        self._lock = threading.Lock()

    def connect(self) -> None:
        self._t.open()

    def disconnect(self) -> None:
        self._t.close()

    def require(self, cap: Cap) -> None:
        if not self.caps.has(cap):
            raise UnsupportedCapability(self.model, cap.name)

    def _send(self, cmd: bytes, payload: bytes = b"") -> None:
        with self._lock:
            self._t.write(self._codec.frame(cmd, payload))

    def _query(self, cmd: bytes, payload: bytes = b"", *, nframes: int = 1):
        self._send(cmd, payload)
        frames: list[bytes] = []
        buffer = b""
        for _ in range(64):
            chunk = self._t.read(256, self._timeout)
            if chunk:
                got, buffer = self._codec.split(buffer + chunk)
                frames.extend(got)
                if len(frames) >= nframes:
                    return frames
            elif frames:
                break
        if not frames:
            raise ProtocolError(f"{self.model}: no reply to {cmd!r}")
        return frames

    def _check_freq(self, hz: float) -> float:
        hz = float(hz)
        if hz <= 0:
            raise OutOfRange(f"{hz} Hz")
        if self.bands and not any(lo <= hz <= hi for lo, hi in self.bands):
            raise OutOfRange(f"{hz / 1e6:.6f} MHz outside {self.model} bands")
        return hz

    def _check_mode(self, mode: str):
        key = mode.upper()
        if key not in self.modes:
            raise ProtocolError(f"{self.model}: unknown mode {mode!r}")
        return self.modes[key]

    def _check_channel(self, channel: int) -> int:
        if not 0 <= int(channel) <= self.max_channel:
            raise OutOfRange(f"channel {channel} outside 0..{self.max_channel}")
        return int(channel)

    def set_frequency(self, hz: float) -> None:
        self.require(Cap.TUNE)
        self._do_set_frequency(self._check_freq(hz))

    def get_frequency(self) -> float:
        self.require(Cap.TUNE)
        return self._do_get_frequency()

    def set_mode(self, mode: str) -> None:
        self.require(Cap.MODE)
        self._do_set_mode(self._check_mode(mode))

    def get_mode(self) -> str:
        self.require(Cap.MODE)
        code = self._do_get_mode()
        for name, val in self.modes.items():
            if val == code:
                return name
        raise ProtocolError(f"{self.model}: unknown mode code {code}")

    def ptt(self, on: bool) -> None:
        self.require(Cap.PTT)
        self._do_ptt(on)

    def vfo_select(self, which: str) -> None:
        self.require(Cap.VFO)
        if which.upper() not in ("A", "B"):
            raise ProtocolError(f"unknown VFO {which!r}")
        self._do_vfo_select(which.upper())

    def vfo_swap(self) -> None:
        self.require(Cap.VFO)
        self._do_vfo_swap()

    def vfo_copy(self) -> None:
        self.require(Cap.VFO)
        self._do_vfo_copy()

    def memory_write(self, mem: Memory) -> None:
        self.require(Cap.MEMORY)
        mem.validate(max_channel=self.max_channel, modes=set(self.modes) or None)
        self._do_memory_write(mem)

    def memory_read(self, channel: int) -> Memory:
        self.require(Cap.MEMORY)
        return self._do_memory_read(self._check_channel(channel))

    def memory_clear(self, channel: int) -> None:
        self.require(Cap.MEMORY)
        self._do_memory_clear(self._check_channel(channel))

    def squelch_open(self):
        self.require(Cap.SQUELCH)
        return self._do_squelch_open()

    def scope_read(self, *, center_hz: float, span_hz: float):
        self.require(Cap.SPECTRUM)
        return self._do_scope_read(center_hz=center_hz, span_hz=span_hz)

    def status(self) -> dict:
        out = {
            "model": self.model, "vendor": self.vendor,
            "caps": self.caps.name, "connected": self._t.is_open,
        }
        for label, fn in (("frequency", self.get_frequency), ("mode", self.get_mode)):
            try:
                out[label] = fn()
            except Exception as exc:
                out[label] = f"err: {exc}"
        return out

    def _do_set_frequency(self, hz: float) -> None: ...
    def _do_get_frequency(self) -> float: ...
    def _do_set_mode(self, code) -> None: ...
    def _do_get_mode(self): ...
    def _do_ptt(self, on: bool) -> None: ...
    def _do_vfo_select(self, which: str) -> None: ...
    def _do_vfo_swap(self) -> None: ...
    def _do_vfo_copy(self) -> None: ...
    def _do_memory_write(self, mem: Memory) -> None: ...
    def _do_memory_read(self, channel: int) -> Memory: ...
    def _do_memory_clear(self, channel: int) -> None: ...
    def _do_squelch_open(self): ...
    def _do_scope_read(self, *, center_hz: float, span_hz: float): ...
