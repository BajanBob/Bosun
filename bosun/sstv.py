"""SSTV (slow-scan television) picture decoder, plus an encoder for testing.

Modes: Martin M1/M2, Scottie S1/S2, Robot 36, PD90/PD120/PD180 (PD120 and
PD180 are what the ISS usually sends). The decoder listens continuously,
detects the VIS header that names the mode, then builds the picture line by
line, re-aligning on each line's sync pulse so timing drift does not slant it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

BLACK, WHITE, SYNC, MID = 1500.0, 2300.0, 1200.0, 1900.0


@dataclass(frozen=True)
class Mode:
    name: str
    vis: int
    width: int
    lines: int            # picture lines
    segments: tuple       # per transmitted line: (kind, ms, freq for fixed tones)
    sync_index: int       # which segment is the line sync
    lines_per_tx: int = 1  # PD sends two picture lines per transmitted line
    lead_ms: float = 0.0   # extra time before the first line (Scottie start sync)
    colour: str = "GBR"    # GBR (Martin/Scottie), YUV (Robot 36), PD

    @property
    def line_ms(self) -> float:
        return sum(s[1] for s in self.segments)

    @property
    def tx_lines(self) -> int:
        return self.lines // self.lines_per_tx

    def offset(self, index: int) -> float:
        return sum(s[1] for s in self.segments[:index])


def _martin(name, vis, scan):
    return Mode(name, vis, 320, 256, (
        ("sync", 4.862, SYNC), ("porch", 0.572, BLACK), ("G", scan, None),
        ("porch", 0.572, BLACK), ("B", scan, None), ("porch", 0.572, BLACK),
        ("R", scan, None), ("porch", 0.572, BLACK)), sync_index=0)


def _scottie(name, vis, scan):
    return Mode(name, vis, 320, 256, (
        ("porch", 1.5, BLACK), ("G", scan, None), ("porch", 1.5, BLACK), ("B", scan, None),
        ("sync", 9.0, SYNC), ("porch", 1.5, BLACK), ("R", scan, None)),
        sync_index=4, lead_ms=9.0)


def _pd(name, vis, width, lines, scan):
    return Mode(name, vis, width, lines, (
        ("sync", 20.0, SYNC), ("porch", 2.08, BLACK), ("Y0", scan, None),
        ("V", scan, None), ("U", scan, None), ("Y1", scan, None)),
        sync_index=0, lines_per_tx=2, colour="PD")


ROBOT36 = Mode("Robot 36", 8, 320, 240, (
    ("sync", 9.0, SYNC), ("porch", 3.0, BLACK), ("Y", 88.0, None),
    ("sep", 4.5, None), ("porch", 1.5, MID), ("C", 44.0, None)),
    sync_index=0, colour="YUV")

MODES = {m.vis: m for m in (
    _martin("Martin M1", 44, 146.432), _martin("Martin M2", 40, 73.216),
    _scottie("Scottie S1", 60, 138.240), _scottie("Scottie S2", 56, 88.064),
    ROBOT36,
    _pd("PD90", 99, 320, 256, 170.240), _pd("PD120", 95, 640, 496, 121.600),
    _pd("PD180", 96, 640, 496, 183.040),
)}
BY_NAME = {m.name: m for m in MODES.values()}


# ------------------------------------------------------------------ encoder
def _tone_track(fs: int):
    freqs: list[np.ndarray] = []
    carry = [0.0]

    def add(freq, ms):
        """Append `ms` of tone; freq is a constant or per-pixel values that
        are stretched to fill exactly that time (sample-exact, no drift)."""
        exact = ms / 1000 * fs + carry[0]
        n = int(exact)
        carry[0] = exact - n
        if n <= 0:
            return
        if np.isscalar(freq):
            freqs.append(np.full(n, freq, np.float32))
        else:
            vals = np.asarray(freq, np.float32)
            idx = np.minimum((np.arange(n) * len(vals) / n).astype(int), len(vals) - 1)
            freqs.append(vals[idx])
    return freqs, add


def _scan(add, values, ms, fs):
    add(BLACK + np.asarray(values, np.float32) / 255 * (WHITE - BLACK), ms)


def encode(image: np.ndarray, mode: Mode, fs: int = 48000) -> np.ndarray:
    """RGB uint8 image (any size; resampled) -> SSTV audio, float32 -1..1."""
    img = np.asarray(image, np.float32)
    ys = np.linspace(0, img.shape[0] - 1, mode.lines).astype(int)
    xs = np.linspace(0, img.shape[1] - 1, mode.width).astype(int)
    img = img[ys][:, xs]
    freqs, add = _tone_track(fs)
    add(MID, 300); add(SYNC, 10); add(MID, 300); add(SYNC, 30)  # noqa: E702
    bits = [(mode.vis >> i) & 1 for i in range(7)]
    bits.append(sum(bits) % 2)
    for b in bits:
        add(1100.0 if b else 1300.0, 30)
    add(SYNC, 30)
    if mode.lead_ms:
        add(SYNC, mode.lead_ms)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    v = (r - y) * 0.713 + 128
    u = (b - y) * 0.564 + 128
    for tx in range(mode.tx_lines):
        row = tx * mode.lines_per_tx
        for kind, ms, freq in mode.segments:
            if kind in ("sync", "porch"):
                add(freq, ms)
            elif kind == "sep":
                add(BLACK if row % 2 == 0 else WHITE, ms)
            elif kind in "GBR":
                chan = {"R": r, "G": g, "B": b}[kind]
                _scan(lambda f, m: add(f, m), chan[row], ms, fs)
            elif kind == "Y" or kind == "Y0":
                _scan(add, np.clip(y[row], 0, 255), ms, fs)
            elif kind == "Y1":
                _scan(add, np.clip(y[row + 1], 0, 255), ms, fs)
            elif kind == "C":
                src = v if row % 2 == 0 else u
                _scan(add, np.clip(src[row], 0, 255), ms, fs)
            elif kind == "V":
                _scan(add, np.clip((v[row] + v[row + 1]) / 2, 0, 255), ms, fs)
            elif kind == "U":
                _scan(add, np.clip((u[row] + u[row + 1]) / 2, 0, 255), ms, fs)
    add(MID, 100)
    track = np.concatenate(freqs)
    phase = 2 * np.pi * np.cumsum(track, dtype=np.float64) / fs  # float32 loses phase
    return (0.8 * np.sin(phase)).astype(np.float32)


# ------------------------------------------------------------------ decoder
def _lowpass(cutoff: float, fs: float, taps: int = 63) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff / fs * n) * np.hamming(taps)
    return (h / h.sum()).astype(np.float32)


class FreqTracker:
    """Audio -> instantaneous tone frequency, decimated to `out_fs`."""

    def __init__(self, fs: int, out_fs: int = 12000) -> None:
        self.fs = fs
        self.decim = max(1, int(round(fs / out_fs)))
        self.out_fs = fs / self.decim
        self.taps = _lowpass(950, fs)
        self._zi = np.zeros(len(self.taps) - 1, np.complex64)
        self._n = 0
        self._prev = np.complex64(1)
        self._phase_off = 0

    def process(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio, np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        n = np.arange(self._n, self._n + len(audio))
        self._n += len(audio)
        mixed = audio * np.exp(-2j * np.pi * MID * n / self.fs).astype(np.complex64)
        buf = np.concatenate([self._zi, mixed])
        filt = np.convolve(buf, self.taps, mode="valid")
        self._zi = buf[-(len(self.taps) - 1):]
        # keep decimation phase continuous across calls
        start = (-self._phase_off) % self.decim
        base = filt[start:: self.decim]
        self._phase_off = (self._phase_off + len(filt)) % self.decim
        if not len(base):
            return np.zeros(0, np.float32)
        prev = np.concatenate([[self._prev], base[:-1]])
        self._prev = base[-1]
        dphi = np.angle(base * np.conj(prev))
        return (MID + dphi * self.out_fs / (2 * np.pi)).astype(np.float32)


def _ycc_to_rgb(y, cr, cb):
    y, cr, cb = (np.asarray(a, np.float32) for a in (y, cr, cb))
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    return np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)


class SSTVDecoder:
    """Feed audio continuously; get callbacks as pictures arrive.

    on_start(mode), on_line(image, line_index), on_done(image, mode)
    """

    def __init__(self, fs: int = 48000, on_start=None, on_line=None, on_done=None) -> None:
        self.track = FreqTracker(fs)
        self.ffs = self.track.out_fs
        self.buf = np.zeros(0, np.float32)
        self.base = 0  # absolute index of buf[0]
        self.on_start: Callable | None = on_start
        self.on_line: Callable | None = on_line
        self.on_done: Callable | None = on_done
        self.mode: Mode | None = None
        self.image: np.ndarray | None = None
        self.status = "Listening for SSTV..."
        self._t0 = 0.0
        self._line = 0
        self._drift = 0.0
        self._chroma = None
        self._search_from = 0

    # -- helpers on absolute sample indices
    def _ms(self, ms: float) -> float:
        return ms / 1000 * self.ffs

    def _seg(self, a: float, b: float) -> np.ndarray:
        i0, i1 = int(a) - self.base, int(b) - self.base
        return self.buf[max(0, i0): max(0, i1)]

    def feed(self, audio: np.ndarray) -> None:
        f = self.track.process(audio)
        if len(f):
            self.buf = np.concatenate([self.buf, f])
        if self.mode is None:
            self._find_vis()
        if self.mode is not None:
            self._decode_lines()

    def _trim(self, keep_from: int) -> None:
        cut = keep_from - self.base
        if cut > 0:
            self.buf = self.buf[cut:]
            self.base += cut

    def _find_vis(self) -> None:
        f = self.buf
        if len(f) < self._ms(900):
            return
        # Smooth over 5 ms and look for: >=200 ms of ~1900 Hz, ~1200 Hz start
        # bit (30 ms), 8 bits, ~1200 Hz stop bit.
        k = max(1, int(self._ms(5)))
        sm = np.convolve(f, np.ones(k) / k, mode="same")
        lead = np.abs(sm - MID) < 120
        low = np.abs(sm - SYNC) < 80
        start = max(0, self._search_from - self.base)
        bit = self._ms(30)
        i = start
        n = len(sm)
        while i < n - int(bit * 10.5):
            if not low[i]:
                i += 1
                continue
            # start of a 1200 Hz run: need ~30 ms of it, preceded by leader
            run_end = i
            while run_end < n and low[run_end]:
                run_end += 1
            run = run_end - i
            if bit * 0.6 <= run <= bit * 1.6 and i > self._ms(200) and \
                    lead[max(0, i - int(self._ms(150))): i - int(self._ms(15))].mean() > 0.8:
                bits = []
                for b in range(8):
                    c = i + bit * (1.5 + b)
                    seg = sm[int(c - bit * 0.3): int(c + bit * 0.3)]
                    bits.append(1 if np.median(seg) < SYNC else 0)
                stop = sm[int(i + bit * 9.2): int(i + bit * 9.8)]
                code = sum(b << j for j, b in enumerate(bits[:7]))
                parity_ok = sum(bits[:7]) % 2 == bits[7]
                if len(stop) and abs(np.median(stop) - SYNC) < 100 and parity_ok \
                        and code in MODES:
                    self._begin(MODES[code], self.base + i + bit * 10)
                    return
                i = run_end
                continue
            i = run_end
        # nothing yet: keep the last ~1.2 s for a header spanning chunks
        self._search_from = max(self.base, self.base + n - int(self._ms(1200)))
        self._trim(self._search_from - int(self._ms(700)))
        self._search_from = max(self._search_from, self.base)

    def _begin(self, mode: Mode, t0: float) -> None:
        self.mode = mode
        self.image = np.zeros((mode.lines, mode.width, 3), np.uint8)
        self._t0 = t0 + self._ms(mode.lead_ms)
        self._line = 0
        self._drift = 0.0
        self._chroma = None
        self.status = f"Receiving {mode.name}..."
        if self.on_start:
            self.on_start(mode)

    def _sync_start(self, expected: float, mode: Mode) -> float | None:
        """Find the sync pulse near `expected`; None if not clear."""
        win = self._ms(mode.line_ms * 0.04 + 2)
        seg = self._seg(expected - win, expected + win + self._ms(mode.segments[
            mode.sync_index][1]))
        if not len(seg):
            return None
        k = max(1, int(self._ms(1)))
        sm = np.convolve(seg, np.ones(k) / k, mode="same")
        low = sm < (SYNC + BLACK) / 2
        need = int(self._ms(mode.segments[mode.sync_index][1]) * 0.6)
        run = 0
        for j, v in enumerate(low):
            run = run + 1 if v else 0
            if run >= need:
                return expected - win + (j - run + 1)
        return None

    def _pixels(self, line_start: float, mode: Mode, index: int) -> np.ndarray:
        """Average the tone over each pixel's time slot (less noise than one
        sample), falling back to interpolation when slots are shorter than a
        sample."""
        a = line_start + self._ms(mode.offset(index)) - self.base
        dur = self._ms(mode.segments[index][1])
        edges = a + np.arange(mode.width + 1) * dur / mode.width
        lo = int(np.floor(edges[0]))
        hi = int(np.ceil(edges[-1])) + 2
        seg = self.buf[max(0, lo): max(0, hi)]
        if len(seg) < 2:
            return np.zeros(mode.width)
        # integral of the piecewise-constant signal at fractional positions
        csum = np.concatenate([[0.0], np.cumsum(seg, dtype=np.float64)])
        pos = np.clip(edges - max(0, lo), 0, len(seg))
        integ = np.interp(pos, np.arange(len(csum)), csum)
        width = np.diff(pos)
        vals = np.where(width > 1e-9, np.diff(integ) / np.maximum(width, 1e-9),
                        np.interp(pos[:-1], np.arange(len(seg)), seg))
        return np.clip((vals - BLACK) / (WHITE - BLACK) * 255, 0, 255)

    def _decode_lines(self) -> None:
        mode = self.mode
        line_len = self._ms(mode.line_ms)
        while self._line < mode.tx_lines:
            nominal = self._t0 + self._line * line_len + self._drift
            end = nominal + line_len + self._ms(mode.line_ms * 0.05 + 3)
            if end - self.base > len(self.buf):
                return  # wait for more audio
            expected_sync = nominal + self._ms(mode.offset(mode.sync_index))
            found = self._sync_start(expected_sync, mode)
            if found is not None:
                err = found - expected_sync
                # follow slow drift, ignore wild jumps from noise
                if abs(err) < self._ms(mode.line_ms * 0.03 + 2):
                    self._drift += 0.5 * err
            start = self._t0 + self._line * line_len + self._drift
            self._emit(start, mode)
            self._line += 1
            self._trim(int(start) - int(self._ms(50)))
        self._finish()

    def _emit(self, start: float, mode: Mode) -> None:
        row = self._line * mode.lines_per_tx
        idx = {s[0]: i for i, s in enumerate(mode.segments)}
        if mode.colour == "GBR":
            g, b, r = (self._pixels(start, mode, idx[c]) for c in "GBR")
            self.image[row] = np.stack([r, g, b], axis=-1).astype(np.uint8)
        elif mode.colour == "YUV":
            y = self._pixels(start, mode, idx["Y"])
            c = self._pixels(start, mode, idx["C"])
            sep = self._seg(start + self._ms(mode.offset(idx["sep"])),
                            start + self._ms(mode.offset(idx["sep"]) + 4.5))
            is_v = (np.median(sep) if len(sep) else BLACK) < MID
            if self._chroma is None:
                self._chroma = {"V": np.full(mode.width, 128.0), "U": np.full(mode.width, 128.0)}
            self._chroma["V" if is_v else "U"] = c
            self.image[row] = _ycc_to_rgb(y, self._chroma["V"], self._chroma["U"])
        else:  # PD
            y0 = self._pixels(start, mode, idx["Y0"])
            v = self._pixels(start, mode, idx["V"])
            u = self._pixels(start, mode, idx["U"])
            y1 = self._pixels(start, mode, idx["Y1"])
            self.image[row] = _ycc_to_rgb(y0, v, u)
            if row + 1 < mode.lines:
                self.image[row + 1] = _ycc_to_rgb(y1, v, u)
        if self.on_line:
            self.on_line(self.image, row)

    def _finish(self) -> None:
        img, mode = self.image, self.mode
        self.status = f"Received {mode.name}. Listening for SSTV..."
        self.mode = None
        self._search_from = self.base
        if self.on_done:
            self.on_done(img, mode)


def read_wav(path: str, fs: int = 48000) -> np.ndarray:
    """Mono float audio from a 8/16/24/32-bit PCM WAV, resampled to fs."""
    import wave

    with wave.open(path, "rb") as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        data = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
    else:
        data = np.frombuffer(raw, "<i4").astype(np.float32) / (1 << 31)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if rate != fs:
        x = np.arange(0, len(data), rate / fs)
        data = np.interp(x, np.arange(len(data)), data).astype(np.float32)
    return data
