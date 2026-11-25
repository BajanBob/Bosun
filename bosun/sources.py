"""IQ sources for the spectrum view: real SDRs and a built-in simulator."""

from __future__ import annotations

import threading
import time

import numpy as np

from .errors import SDRUnavailable

DEFAULT_RATE = 2.048e6


class IQSource:
    name = "abstract"
    rate = DEFAULT_RATE
    center_hz = 100e6
    min_hz, max_hz = 0.0, 6e9

    def open(self) -> None: ...
    def close(self) -> None: ...
    def tune(self, hz: float) -> None:
        self.center_hz = float(hz)

    def set_gain(self, db: float) -> None: ...
    def read(self, n: int) -> np.ndarray:
        raise NotImplementedError


class DemoSource(IQSource):
    """Simulated band: steady carriers, a voice-like FM channel that keys up and
    down, a broadcast station and noise. For trying Bosun without hardware."""

    name = "Demo (simulated signals)"

    def __init__(self, center_hz: float = 145.0e6, rate: float = DEFAULT_RATE,
                 seed: int | None = None) -> None:
        self.center_hz, self.rate = center_hz, rate
        self._rng = np.random.default_rng(seed)
        self._t0 = time.monotonic()
        self._phase = 0.0

    def _emitters(self, now: float):
        # (absolute Hz, amplitude, kind, on?)
        return [
            (145.500e6, 0.05, "fm", (now % 6) < 3.5),          # repeater keying
            (145.800e6, 0.02, "cw", True),                      # beacon
            (144.390e6, 0.015, "fm", (now % 10) < 1.2),          # packet burst
            (146.520e6, 0.03, "fm", (now % 9) > 5),
            (100.1e6, 0.2, "wfm", True),                        # FM broadcast
            (121.500e6, 0.04, "am", (now % 7) < 4),             # airband
            (14.074e6, 0.01, "narrow", True),                   # FT8-ish
            (7.100e6, 0.03, "ssb", (now % 5) < 3),
        ]

    def _voice(self, n: int, bw_hz: float) -> np.ndarray:
        """Band-limited random 'audio', -1..1."""
        taps = max(2, int(self.rate / bw_hz))
        x = np.convolve(self._rng.standard_normal(n + taps), np.ones(taps) / taps, "valid")[:n]
        return (x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)

    def read(self, n: int) -> np.ndarray:
        t = (np.arange(n) + self._phase) / self.rate
        self._phase += n
        noise = (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n)) * 0.002
        out = noise.astype(np.complex64)
        now = time.monotonic() - self._t0
        half = self.rate / 2
        for hz, amp, kind, on in self._emitters(now):
            off = hz - self.center_hz
            if not on or abs(off) > half * 0.98:
                continue
            carrier = 2 * np.pi * off * t
            if kind == "cw":
                sig = np.exp(1j * carrier)
            elif kind in ("fm", "wfm"):
                dev = 2_500 if kind == "fm" else 60_000
                audio = self._voice(n, 3_000 if kind == "fm" else 15_000)
                phase = 2 * np.pi * dev * np.cumsum(audio) / self.rate
                sig = np.exp(1j * (carrier + phase))
            elif kind == "am":
                sig = (1 + 0.5 * self._voice(n, 3_000)) * np.exp(1j * carrier)
            elif kind == "ssb":
                tones = sum(np.exp(2j * np.pi * f * t) * a for f, a in
                            ((400, 1), (900, .8), (1700, .6), (2400, .4)))
                sig = tones * np.exp(1j * carrier) / 2.8
            else:
                sig = np.exp(1j * (carrier + 2 * np.pi * 25 * np.sin(2 * np.pi * 3 * t) / 3))
            out += (amp * sig).astype(np.complex64)
        return out


class SDRSource(IQSource):
    """Any Bosun SDR backend (RTL-SDR, SoapySDR devices, Airspy)."""

    def __init__(self, spec: str, center_hz: float = 100e6, rate: float = DEFAULT_RATE,
                 gain_db: float = 30.0) -> None:
        self.spec, self.center_hz, self.rate, self.gain = spec, center_hz, rate, gain_db
        self.name = spec
        self._dev = None
        self._lock = threading.Lock()

    def open(self) -> None:
        from .sdr import open_backend

        try:
            self._dev = open_backend(self.spec)
            self._dev.set_sample_rate(self.rate)
            self._dev.set_frequency(self.center_hz)
            self._dev.set_gain(self.gain)
            caps = self._dev.caps
            if caps.max_hz:
                self.min_hz, self.max_hz = caps.min_hz, caps.max_hz
        except SDRUnavailable:
            raise
        except Exception as exc:
            raise SDRUnavailable(f"cannot open {self.spec}: {exc}") from exc

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def tune(self, hz: float) -> None:
        self.center_hz = float(hz)
        if self._dev is not None:
            with self._lock:
                self._dev.set_frequency(self.center_hz)

    def set_gain(self, db: float) -> None:
        self.gain = db
        if self._dev is not None:
            with self._lock:
                self._dev.set_gain(db)

    def read(self, n: int) -> np.ndarray:
        if self._dev is None:
            raise SDRUnavailable("SDR not open")
        with self._lock:
            blocks, got = [], 0
            for block in self._dev.stream(n):
                blocks.append(block)
                got += len(block)
                if got >= n:
                    break
        return np.concatenate(blocks)[:n] if blocks else np.zeros(n, np.complex64)


def list_sources() -> list[str]:
    """Names for the source picker: the demo plus any SDRs found."""
    names = [DemoSource.name]
    try:
        from .sdr import available

        for key, devs in available().items():
            if key == "file":
                continue
            names += [d if d.startswith(f"{key}:") else f"{key}:{d}" for d in devs]
    except Exception:
        pass
    return names


def open_source(name: str, center_hz: float, rate: float = DEFAULT_RATE,
                gain_db: float = 30.0) -> IQSource:
    if name == DemoSource.name or not name:
        src: IQSource = DemoSource(center_hz, rate)
    else:
        src = SDRSource(name, center_hz, rate, gain_db)
    src.open()
    return src
