"""Cognitive receiver: learns the band, tracks signals, and sweeps wide ranges.

The receiver keeps a slowly adapting noise floor and per-bin occupancy, so its
detection threshold follows the band instead of a fixed number. Signals are
tracked across frames (first heard, last heard, how often on, strongest SNR),
which lets it flag new signals and rank the busiest channels.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field

import numpy as np

from . import dsp


@dataclass
class TrackedSignal:
    center_hz: float
    bandwidth_hz: float
    kind: str
    hint: str
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    frames_seen: int = 1
    frames_total: int = 1
    best_snr_db: float = 0.0
    last_snr_db: float = 0.0

    @property
    def activity(self) -> float:
        """Share of frames (since first heard) in which it was on, 0-1."""
        return self.frames_seen / max(1, self.frames_total)

    @property
    def active(self) -> bool:
        return time.time() - self.last_seen < 2.0

    def describe(self) -> str:
        state = "ON " if self.active else "off"
        return (f"{state} {self.center_hz / 1e6:11.5f} MHz  {self.kind:<18} "
                f"{self.best_snr_db:4.0f} dB  busy {self.activity:4.0%}")


class CognitiveReceiver:
    def __init__(self, *, sensitivity: float = 0.5, learn_rate: float = 0.05,
                 match_hz: float | None = None) -> None:
        # sensitivity 0 (only strong signals) .. 1 (pick up weak ones)
        self.sensitivity = sensitivity
        self.learn_rate = learn_rate
        self.match_hz = match_hz
        self.floor: np.ndarray | None = None
        self.occupancy: np.ndarray | None = None
        self.signals: list[TrackedSignal] = []
        self.frames = 0
        self._span: tuple[float, float, int] | None = None

    def reset(self) -> None:
        self.floor = self.occupancy = None
        self.signals.clear()
        self.frames = 0

    @property
    def threshold_db(self) -> float:
        return 12.0 - 8.0 * max(0.0, min(1.0, self.sensitivity))

    def process(self, offsets_hz: np.ndarray, power_db: np.ndarray,
                center_hz: float) -> list[dsp.Detection]:
        span = (center_hz, float(offsets_hz[-1] - offsets_hz[0]), len(power_db))
        if span != self._span:
            # Retuned: relearn the floor for the new view; keep the signal log.
            self.floor = self.occupancy = None
            self._span = span
        local = dsp.noise_floor(power_db)
        if self.floor is None:
            self.floor = local.copy()
            self.occupancy = np.zeros_like(power_db)
        else:
            # Learn the floor only where the band is quiet, so signals do not
            # raise it; drop quickly when the band gets quieter.
            quiet = power_db - self.floor < self.threshold_db
            rate = np.where(quiet, self.learn_rate, self.learn_rate * 0.05)
            self.floor += rate * (local - self.floor)
            self.floor = np.minimum(self.floor, local + 1.0)
        found = dsp.detect(offsets_hz, power_db, center_hz,
                           threshold_db=self.threshold_db, floor=self.floor)
        hot = (power_db - self.floor) > self.threshold_db
        self.occupancy += 0.02 * (hot.astype(np.float32) - self.occupancy)
        self.frames += 1
        self._track(found)
        return found

    def _track(self, found: list[dsp.Detection]) -> None:
        now = time.time()
        for sig in self.signals:
            sig.frames_total += 1
        for det in found:
            tol = self.match_hz or max(det.bandwidth_hz * 0.75, 2_000)
            match = next((s for s in self.signals
                          if abs(s.center_hz - det.center_hz) <= tol), None)
            if match is None:
                self.signals.append(TrackedSignal(
                    det.center_hz, det.bandwidth_hz, det.kind, det.hint,
                    best_snr_db=det.snr_db, last_snr_db=det.snr_db))
                continue
            match.last_seen = now
            match.frames_seen += 1
            match.last_snr_db = det.snr_db
            match.best_snr_db = max(match.best_snr_db, det.snr_db)
            # Refine the estimate slowly.
            match.center_hz += 0.2 * (det.center_hz - match.center_hz)
            match.bandwidth_hz += 0.2 * (det.bandwidth_hz - match.bandwidth_hz)
            match.kind, match.hint = det.kind, det.hint

    def new_signals(self, within_s: float = 5.0) -> list[TrackedSignal]:
        now = time.time()
        return [s for s in self.signals if now - s.first_seen < within_s]

    def ranked(self) -> list[TrackedSignal]:
        """Active first, then busiest, then strongest."""
        return sorted(self.signals, key=lambda s: (not s.active, -s.activity,
                                                   -s.best_snr_db))

    def export_csv(self, path: str) -> int:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frequency_mhz", "bandwidth_khz", "type", "what_it_may_be",
                        "best_snr_db", "busy_percent", "first_heard_utc", "last_heard_utc"])
            for s in self.ranked():
                w.writerow([f"{s.center_hz / 1e6:.6f}", f"{s.bandwidth_hz / 1e3:.2f}",
                            s.kind, s.hint, f"{s.best_snr_db:.1f}",
                            f"{100 * s.activity:.0f}",
                            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(s.first_seen)),
                            time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(s.last_seen))])
        return len(self.signals)


class Sweeper:
    """Steps an IQ source across a range wider than one view and stitches it."""

    def __init__(self, source, start_hz: float, stop_hz: float, *, nfft: int = 2048,
                 usable: float = 0.8) -> None:
        if stop_hz <= start_hz:
            raise ValueError("stop must be above start")
        self.source, self.start_hz, self.stop_hz = source, start_hz, stop_hz
        self.nfft, self.usable = nfft, usable
        step = source.rate * usable
        self.centers = list(np.arange(start_hz + step / 2, stop_hz + step / 2, step))

    def sweep(self, settle_s: float = 0.0, stop_flag=None):
        """Returns (absolute_hz, power_db) for the whole range."""
        freqs, powers = [], []
        keep = self.usable / 2
        for c in self.centers:
            if stop_flag is not None and stop_flag():
                break
            self.source.tune(c)
            if settle_s:
                time.sleep(settle_s)
            self.source.read(self.nfft)  # flush after retune
            off, p = dsp.psd(self.source.read(self.nfft * 8), self.source.rate, self.nfft)
            mask = np.abs(off) <= self.source.rate * keep
            freqs.append(off[mask] + c)
            powers.append(p[mask])
        if not freqs:
            return np.array([]), np.array([])
        f, p = np.concatenate(freqs), np.concatenate(powers)
        inside = (f >= self.start_hz) & (f <= self.stop_hz)
        return f[inside], p[inside]
