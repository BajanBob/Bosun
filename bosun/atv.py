"""Analogue video (PAL / NTSC, black and white) from IQ: FPV (FM) and broadcast (AM).

The decoder demodulates, finds horizontal sync pulses and the broad vertical
sync pulses, and builds one field at a time. Colour is not decoded. A
synthesiser produces test video for the built-in test source and the tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SYNC_LEVEL, BLACK_LEVEL, WHITE_LEVEL = 0.0, 0.3, 1.0


@dataclass(frozen=True)
class Standard:
    name: str
    lines: int          # per frame
    fps: float
    line_us: float
    hsync_us: float
    back_porch_us: float
    active_us: float

    @property
    def field_lines(self) -> int:
        return self.lines // 2

    @property
    def field_hz(self) -> float:
        return self.fps * 2


PAL = Standard("PAL", 625, 25.0, 64.0, 4.7, 5.7, 52.0)
NTSC = Standard("NTSC", 525, 29.97, 63.556, 4.7, 4.7, 52.6)
STANDARDS = {"PAL": PAL, "NTSC": NTSC}

# Analogue FPV video channels (MHz). 5.8 GHz Raceband is the common worldwide
# set; check what is permitted where you are before transmitting.
FPV_CHANNELS = {f"5.8G Raceband R{i + 1}": f for i, f in enumerate(
    (5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917))}
FPV_CHANNELS.update({f"5.8G Band A{i + 1}": f for i, f in enumerate(
    (5865, 5845, 5825, 5805, 5785, 5765, 5745, 5725))})
FPV_CHANNELS.update({f"1.3G ch{i + 1}": f for i, f in enumerate(
    (1080, 1120, 1160, 1200, 1240, 1280, 1320, 1360))})


# ------------------------------------------------------------------ synthesis
def composite_field(img: np.ndarray, std: Standard, fs: float, odd: bool = False
                    ) -> np.ndarray:
    """One field of composite video (levels 0..1) from a grey image (0..255)."""
    spl = std.line_us * 1e-6 * fs
    n_lines = std.field_lines
    total = int(round(spl * (n_lines + (0.5 if odd else 0))))
    out = np.full(total, BLACK_LEVEL, np.float32)
    hs = int(std.hsync_us * 1e-6 * fs)
    act0 = (std.hsync_us + std.back_porch_us) * 1e-6 * fs
    act_n = std.active_us * 1e-6 * fs
    first_video, vsync_lines = 22, 3
    rows = np.linspace(0, img.shape[0] - 1, n_lines - first_video).astype(int)
    for ln in range(n_lines):
        a = int(round(ln * spl))
        if ln < vsync_lines:  # broad pulses: long low, short high, twice per line
            for half in (0, 1):
                b = a + int(half * spl / 2)
                out[b: b + int(spl / 2 - hs)] = SYNC_LEVEL
            continue
        out[a: a + hs] = SYNC_LEVEL
        if ln >= first_video:
            row = img[rows[ln - first_video]].astype(np.float32) / 255
            xs = np.arange(int(act_n))
            vals = row[np.minimum((xs * len(row) / act_n).astype(int), len(row) - 1)]
            s0 = a + int(act0)
            out[s0: s0 + len(vals)] = BLACK_LEVEL + vals * (WHITE_LEVEL - BLACK_LEVEL)
    return out


def modulate(video: np.ndarray, fs: float, mode: str = "FM", deviation: float = 2.0e6,
             phase0: float = 0.0) -> tuple[np.ndarray, float]:
    """Composite (0..1) -> complex baseband IQ. Returns (iq, end phase)."""
    if mode.upper() == "FM":
        f = (video - 0.5) * 2 * deviation
        ph = phase0 + 2 * np.pi * np.cumsum(f, dtype=np.float64) / fs
        return np.exp(1j * ph).astype(np.complex64), float(ph[-1] % (2 * np.pi))
    # AM with negative modulation (sync = full carrier), as broadcast TV
    amp = 1.0 - 0.75 * video
    return amp.astype(np.complex64), phase0


def test_pattern(t: float, h: int = 288, w: int = 360) -> np.ndarray:
    img = np.zeros((h, w), np.uint8)
    for i in range(8):  # grey bars
        img[: h // 2, i * w // 8:(i + 1) * w // 8] = 255 - i * 32
    img[h // 2:] = np.linspace(0, 255, w)[None, :].astype(np.uint8)
    x = int((t * 80) % w)  # moving white bar so motion is visible
    img[h // 2 - 20: h // 2 + 20, max(0, x - 8): x + 8] = 255
    yy, xx = np.ogrid[:h, :w]  # circle
    img[np.abs(np.hypot(yy - h * 0.72, xx - w / 2) - 50) < 3] = 0
    return img


# ------------------------------------------------------------------ decoding
class ATVDecoder:
    """Feed IQ blocks; returns completed fields as uint8 greyscale images."""

    def __init__(self, fs: float, standard: Standard = PAL, mode: str = "FM",
                 invert: bool = False, width: int = 640) -> None:
        self.fs, self.std, self.mode, self.invert = fs, standard, mode.upper(), invert
        self.width = width
        self.spl = standard.line_us * 1e-6 * fs
        self._prev = np.complex64(1)
        self.buf = np.zeros(0, np.float32)
        self.base = 0
        self.lo, self.hi = None, None
        self.lines: list[np.ndarray] = []
        self.in_field = False
        self.last_sync: float | None = None
        self.fields = 0
        self.lock = 0.0  # share of lines with a sync where expected (0..1)
        self._sync_hits = self._sync_total = 0
        act_n = standard.active_us * 1e-6 * fs
        self._px = (np.arange(width) * (act_n - 1) / max(width - 1, 1)).astype(np.int64)

    def _demod(self, iq: np.ndarray) -> np.ndarray:
        iq = np.asarray(iq, np.complex64)
        if self.mode == "FM":
            prev = np.concatenate([[self._prev], iq[:-1]])
            self._prev = iq[-1] if len(iq) else self._prev
            v = np.angle(iq * np.conj(prev)).astype(np.float32)
        else:
            v = -np.abs(iq).astype(np.float32)  # negative modulation: sync = max
        return -v if self.invert else v

    def _normalise(self, v: np.ndarray) -> np.ndarray:
        sub = v[::16] if len(v) > 4096 else v
        lo, hi = np.percentile(sub, [0.5, 99.5])
        if self.lo is None:
            self.lo, self.hi = lo, hi
        else:
            self.lo += 0.2 * (lo - self.lo)
            self.hi += 0.2 * (hi - self.hi)
        span = max(self.hi - self.lo, 1e-9)
        return ((v - self.lo) / span).astype(np.float32)

    def process(self, iq: np.ndarray) -> list[np.ndarray]:
        v = self._normalise(self._demod(iq))
        # light smoothing (about 0.4 us) against noise
        k = max(1, int(self.fs * 0.4e-6))
        if k > 1:
            v = np.convolve(v, np.ones(k, np.float32) / k, mode="same")
        self.buf = np.concatenate([self.buf, v])
        out = []
        # Sync detection with hysteresis: enter below 0.15, leave above 0.3, so
        # noise riding on the sync tip does not chop pulses into pieces.
        state = np.full(len(self.buf), -1, np.int64)
        state[self.buf < 0.15] = 1
        state[self.buf > 0.30] = 0
        idx = np.where(state >= 0, np.arange(len(state)), 0)
        np.maximum.accumulate(idx, out=idx)
        low = state[idx] == 1
        low[: np.argmax(state >= 0)] = False
        edges = np.flatnonzero(low[1:] & ~low[:-1]) + 1  # falling into sync
        rises = np.flatnonzero(~low[1:] & low[:-1]) + 1
        hs_min, hs_max = 0.5 * self.std.hsync_us, 2.2 * self.std.hsync_us
        broad_min = 0.3 * self.std.line_us
        act0 = (self.std.hsync_us + self.std.back_porch_us) * 1e-6 * self.fs
        act_n = self.std.active_us * 1e-6 * self.fs
        consumed = 0
        for e in edges:
            r = rises[rises > e]
            if not len(r):
                break
            width_us = (r[0] - e) / self.fs * 1e6
            if width_us >= broad_min:  # vertical sync: field boundary
                if self.in_field and len(self.lines) > self.std.field_lines * 0.5:
                    out.append(self._field())
                self.lines, self.in_field = [], False
                self.last_sync = None
                consumed = r[0]
                continue
            if not hs_min <= width_us <= hs_max:
                consumed = r[0]
                continue
            # horizontal sync: one line, if a full line follows
            if e + act0 + act_n >= len(self.buf):
                break
            if self.last_sync is not None:
                gap = (self.base + e - self.last_sync) / self.spl
                self._sync_total += 1
                if 0.9 < gap < 1.1:
                    self._sync_hits += 1
                if gap < 0.8:  # equalising pulse or noise: skip
                    consumed = r[0]
                    continue
            self.last_sync = self.base + e
            self.in_field = True
            line = self.buf[int(e + act0) + self._px]
            self.lines.append(self._lut(line))
            consumed = r[0]
        if self._sync_total >= 50:
            self.lock = self._sync_hits / self._sync_total
            self._sync_hits = self._sync_total = 0
        keep = max(consumed, len(self.buf) - int(self.spl * 3))
        self.buf = self.buf[keep:]
        self.base += keep
        return out

    @staticmethod
    def _lut(line: np.ndarray) -> np.ndarray:
        return np.clip((line - BLACK_LEVEL) * (255 / (WHITE_LEVEL - BLACK_LEVEL)), 0,
                       255).astype(np.uint8)

    def _field(self) -> np.ndarray:
        self.fields += 1
        img = np.stack(self.lines[: self.std.field_lines])
        # skip the blanking lines at the top (no picture)
        top = 17 if len(img) > 40 else 0
        img = img[top:]
        return np.repeat(img, 2, axis=0)  # double lines -> 4:3-ish frame


class ATVTestSource:
    """IQ source transmitting a moving test pattern (for trying the viewer)."""

    name = "Test pattern (simulated)"
    max_rate = 20e6

    def __init__(self, rate: float = 8e6, standard: Standard = PAL, mode: str = "FM",
                 noise: float = 0.05) -> None:
        self.rate, self.std, self.mode, self.noise = rate, standard, mode, noise
        self.center_hz = 5806e6
        self._buf = np.zeros(0, np.complex64)
        self._phase = 0.0
        self._t = 0.0
        self._odd = False
        self._rng = np.random.default_rng(3)

    def open(self) -> None: ...
    def close(self) -> None: ...

    def tune(self, hz: float) -> None:
        self.center_hz = hz

    def set_gain(self, db: float) -> None: ...

    def read(self, n: int) -> np.ndarray:
        while len(self._buf) < n:
            video = composite_field(test_pattern(self._t), self.std, self.rate, self._odd)
            self._odd = not self._odd
            self._t += 1 / self.std.field_hz
            iq, self._phase = modulate(video, self.rate, self.mode, phase0=self._phase)
            if self.noise:
                iq = iq + (self._rng.standard_normal(len(iq)) + 1j *
                           self._rng.standard_normal(len(iq))).astype(np.complex64) \
                    * self.noise
            self._buf = np.concatenate([self._buf, iq.astype(np.complex64)])
        out, self._buf = self._buf[:n], self._buf[n:]
        return out
