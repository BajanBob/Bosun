"""Spectrum + waterfall as PNG bytes using only numpy and the standard library.

Used by Bosun Mobile, where Pillow is not needed.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

BG = np.array([12, 22, 36], np.uint8)
GRID = np.array([40, 60, 80], np.uint8)
TRACE = np.array([56, 198, 214], np.uint8)
FILL = np.array([20, 70, 90], np.uint8)
MARK = np.array([255, 196, 61], np.uint8)
SELECT = np.array([255, 80, 80], np.uint8)
_STOPS = np.array([
    [0.00, 8, 12, 40], [0.25, 30, 60, 140], [0.50, 40, 160, 170],
    [0.75, 240, 210, 60], [1.00, 255, 255, 255]], dtype=np.float32)
PALETTE = np.stack([np.interp(np.linspace(0, 1, 256), _STOPS[:, 0], _STOPS[:, c])
                    for c in (1, 2, 3)], axis=1).astype(np.uint8)


def png_bytes(rgb: np.ndarray, level: int = 1) -> bytes:
    """Encode an HxWx3 uint8 array as PNG."""
    h, w, _ = rgb.shape
    raw = np.empty((h, 1 + w * 3), np.uint8)
    raw[:, 0] = 0  # filter: none
    raw[:, 1:] = rgb.reshape(h, w * 3)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), level))
            + chunk(b"IEND", b""))


def _resample_peak(power_db: np.ndarray, width: int) -> np.ndarray:
    n = len(power_db)
    edges = np.linspace(0, n, width + 1).astype(int)
    edges[1:] = np.maximum(edges[1:], edges[:-1] + 1)
    edges = np.minimum(edges, n)
    return np.maximum.reduceat(power_db, np.minimum(edges[:-1], n - 1)).astype(np.float32)


class Waterfall:
    """Keeps history and draws spectrum (top) + waterfall (bottom)."""

    def __init__(self, width: int = 480, spec_h: int = 110, water_h: int = 170) -> None:
        self.w, self.spec_h, self.water_h = width, spec_h, water_h
        self.water = np.full((water_h, width), -120.0, np.float32)
        self.lo, self.hi = -100.0, -20.0
        self.freqs: np.ndarray | None = None

    def push(self, freqs_hz: np.ndarray, power_db: np.ndarray) -> None:
        row = _resample_peak(np.asarray(power_db, np.float32), self.w)
        self.freqs = np.asarray(freqs_hz)
        lo, hi = float(np.percentile(row, 5)) - 8, float(row.max()) + 5
        self.lo += 0.15 * (lo - self.lo)
        self.hi += 0.15 * (max(hi, lo + 30) - self.hi)
        self.water = np.roll(self.water, 1, axis=0)
        self.water[0] = row

    def x_of(self, hz: float) -> int | None:
        if self.freqs is None:
            return None
        f0, f1 = float(self.freqs[0]), float(self.freqs[-1])
        if not f0 <= hz <= f1:
            return None
        return int((hz - f0) / (f1 - f0) * (self.w - 1))

    def render(self, detections=(), selected_hz: float | None = None) -> np.ndarray:
        img = np.empty((self.spec_h + self.water_h, self.w, 3), np.uint8)
        img[:] = BG
        rng = max(self.hi - self.lo, 1.0)
        # grid every 10 dB and every eighth of the width
        for db in range(int(np.ceil(self.lo / 10) * 10), int(self.hi) + 1, 10):
            y = int((1 - (db - self.lo) / rng) * (self.spec_h - 1))
            if 0 <= y < self.spec_h:
                img[y, :] = GRID
        img[: self.spec_h, :: max(1, self.w // 8)] = GRID
        # spectrum: filled area under the trace
        row = self.water[0]
        ys = ((1 - (row - self.lo) / rng) * (self.spec_h - 1)).clip(0, self.spec_h - 1)
        ys = ys.astype(int)
        yy = np.arange(self.spec_h)[:, None]
        below = yy >= ys[None, :]
        img[: self.spec_h][below] = FILL
        img[ys, np.arange(self.w)] = TRACE
        # waterfall
        norm = ((self.water - self.lo) / rng).clip(0, 1)
        img[self.spec_h:] = PALETTE[(norm * 255).astype(np.uint8)]
        for d in detections:
            x = self.x_of(d.center_hz)
            if x is not None:
                img[0:6, max(0, x - 2): x + 3] = MARK
        if selected_hz is not None:
            x = self.x_of(selected_hz)
            if x is not None:
                img[:, x] = SELECT
        return img

    def png(self, detections=(), selected_hz: float | None = None) -> bytes:
        return png_bytes(self.render(detections, selected_hz))
