"""Spectrum + waterfall images (Pillow). Used for the live view and PNG capture."""

from __future__ import annotations

import datetime as _dt

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Dark background, cyan trace, perceptual waterfall palette.
BG = (12, 22, 36)
GRID = (40, 60, 80)
TEXT = (200, 215, 230)
TRACE = (56, 198, 214)
FLOOR = (120, 120, 160)
MARK = (255, 196, 61)
NEW = (255, 99, 132)
_STOPS = np.array([
    [0.00, 8, 12, 40], [0.25, 30, 60, 140], [0.50, 40, 160, 170],
    [0.75, 240, 210, 60], [1.00, 255, 255, 255]], dtype=np.float32)


def _palette() -> np.ndarray:
    x = np.linspace(0, 1, 256)
    return np.stack([np.interp(x, _STOPS[:, 0], _STOPS[:, c]) for c in (1, 2, 3)],
                    axis=1).astype(np.uint8)


PALETTE = _palette()


def _font(size: int = 12):
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def nice_step(span: float, target: int = 8) -> float:
    raw = span / target
    mag = 10 ** np.floor(np.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return float(m * mag)
    return float(10 * mag)


class SpectrumView:
    """Holds the waterfall history and draws frames."""

    def __init__(self, width: int = 900, height: int = 460, spectrum_frac: float = 0.45,
                 history: int = 300) -> None:
        self.width, self.height = width, height
        self.spec_h = int(height * spectrum_frac)
        self.left, self.bottom = 48, 18
        self.history = history
        self.water: np.ndarray | None = None
        self.db_min, self.db_max = -120.0, -20.0
        self.font = _font(11)
        self.last: tuple[np.ndarray, np.ndarray] | None = None
        self.auto_range = True

    @property
    def plot_w(self) -> int:
        return self.width - self.left

    def resize(self, width: int, height: int) -> None:
        if (width, height) != (self.width, self.height) and width > 200 and height > 150:
            self.width, self.height = width, height
            self.spec_h = int(height * 0.45)
            self.water = None

    def x_to_hz(self, x: float) -> float | None:
        if self.last is None or x < self.left:
            return None
        f = self.last[0]
        return float(f[0] + (x - self.left) / self.plot_w * (f[-1] - f[0]))

    def level_at(self, hz: float) -> float | None:
        if self.last is None:
            return None
        f, p = self.last
        i = int(np.clip(np.searchsorted(f, hz), 0, len(p) - 1))
        return float(p[i])

    def _resample(self, power_db: np.ndarray) -> np.ndarray:
        # Peak-hold resample to the plot width so narrow signals stay visible.
        n, w = len(power_db), self.plot_w
        if n == w:
            return power_db
        edges = np.linspace(0, n, w + 1).astype(int)
        edges[-1] = n
        return np.array([power_db[a:max(b, a + 1)].max() for a, b in
                         zip(edges[:-1], edges[1:], strict=True)], dtype=np.float32)

    def push(self, freqs_hz: np.ndarray, power_db: np.ndarray) -> None:
        self.last = (np.asarray(freqs_hz), np.asarray(power_db))
        if self.auto_range and len(power_db):
            lo, hi = np.percentile(power_db, 5) - 10, np.max(power_db) + 5
            self.db_min += 0.1 * (lo - self.db_min)
            self.db_max += 0.1 * (max(hi, lo + 30) - self.db_max)
        row = self._resample(np.asarray(power_db, dtype=np.float32))
        water_h = self.height - self.spec_h - self.bottom
        if self.water is None or self.water.shape != (water_h, self.plot_w):
            self.water = np.full((max(water_h, 1), self.plot_w), self.db_min, np.float32)
        self.water = np.roll(self.water, 1, axis=0)
        self.water[0] = row

    def image(self, detections=None, floor_db: np.ndarray | None = None,
              title: str = "", marker_hz: float | None = None,
              new_hz: set | None = None) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), BG)
        d = ImageDraw.Draw(img)
        if self.last is None:
            d.text((self.left + 10, 10), "No signal source running", fill=TEXT, font=self.font)
            return img
        freqs, power = self.last
        f0, f1 = float(freqs[0]), float(freqs[-1])
        span = max(f1 - f0, 1.0)
        rng = max(self.db_max - self.db_min, 1.0)
        top, sh = 4, self.spec_h - 8

        def fx(hz):
            return self.left + (hz - f0) / span * self.plot_w

        def py(db):
            return top + sh * (1 - (db - self.db_min) / rng)

        # dB grid
        step_db = nice_step(rng, 5)
        db = np.ceil(self.db_min / step_db) * step_db
        while db <= self.db_max:
            y = py(db)
            d.line([(self.left, y), (self.width, y)], fill=GRID)
            d.text((2, y - 6), f"{db:.0f}", fill=TEXT, font=self.font)
            db += step_db
        # frequency grid
        step_hz = nice_step(span, max(3, self.plot_w // 110))
        hz = np.ceil(f0 / step_hz) * step_hz
        while hz <= f1:
            x = fx(hz)
            d.line([(x, top), (x, self.height - self.bottom)], fill=GRID)
            label = f"{hz / 1e6:.4f}".rstrip("0").rstrip(".")
            d.text((x + 2, self.height - self.bottom + 3), label, fill=TEXT, font=self.font)
            hz += step_hz

        row = self._resample(power)
        xs = self.left + np.arange(len(row))
        pts = list(zip(xs.tolist(), py(row).clip(top, top + sh).tolist(), strict=True))
        if floor_db is not None and len(floor_db) == len(power):
            fl = self._resample(floor_db)
            d.line(list(zip(xs.tolist(), py(fl).clip(top, top + sh).tolist(), strict=True)),
                   fill=FLOOR, width=1)
        d.line(pts, fill=TRACE, width=1)

        # waterfall
        if self.water is not None:
            norm = ((self.water - self.db_min) / rng).clip(0, 1)
            wf = Image.fromarray(PALETTE[(norm * 255).astype(np.uint8)], "RGB")
            img.paste(wf, (self.left, self.spec_h))

        for det in detections or []:
            x = fx(det.center_hz)
            if not self.left <= x <= self.width:
                continue
            half = max(det.bandwidth_hz / span * self.plot_w / 2, 2)
            colour = NEW if new_hz and det.center_hz in new_hz else MARK
            d.rectangle([x - half, top, x + half, top + 4], fill=colour)
            d.text((x + 3, top + 6), det.kind, fill=colour, font=self.font)
        if marker_hz is not None and f0 <= marker_hz <= f1:
            x = fx(marker_hz)
            d.line([(x, top), (x, self.height - self.bottom)], fill=(255, 80, 80), width=1)
        if title:
            d.text((self.left + 6, top + sh - 14), title, fill=TEXT, font=self.font)
        return img

    def capture(self, path: str, **kwargs) -> str:
        img = self.image(**kwargs)
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        d = ImageDraw.Draw(img)
        d.text((self.width - 190, 6), f"Bosun  {stamp}", fill=TEXT, font=self.font)
        img.save(path)
        return path
