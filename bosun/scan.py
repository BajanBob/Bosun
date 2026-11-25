"""Scan engine. Owns timing; hit detection is injected."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .errors import ScanError
from .memory import MemoryBank

RESUME_MODES = ("time", "stop", "off")


@dataclass
class ScanStats:
    cycles: int = 0
    steps: int = 0
    hits: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


class ScanEngine:
    def __init__(
        self, radio, *, mode: str = "list", dwell: float = 0.6,
        resume: str = "time", resume_after: float = 3.0, detector=None,
        on_step=None, on_hit=None, max_cycles: int = 0,
    ) -> None:
        if mode not in ("list", "range"):
            raise ScanError(f"unknown mode {mode!r}")
        if resume not in RESUME_MODES:
            raise ScanError(f"unknown resume {resume!r}")
        if dwell <= 0:
            raise ScanError("dwell must be positive")
        self.radio = radio
        self.mode, self.dwell, self.resume = mode, dwell, resume
        self.resume_after, self.detector = resume_after, detector
        self.on_step, self.on_hit = on_step, on_hit
        self.max_cycles = max_cycles
        self.bank: MemoryBank | None = None
        self.start_hz = self.stop_hz = self.step_hz = None
        self.lockouts: set[float] = set()
        self.stats = ScanStats()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread = None

    def use_bank(self, bank: MemoryBank) -> None:
        self.bank, self.mode = bank, "list"

    def use_range(self, start_hz: float, stop_hz: float, step_hz: float) -> None:
        if step_hz <= 0:
            raise ScanError("step must be positive")
        if stop_hz < start_hz:
            raise ScanError("stop must not be below start")
        self.start_hz, self.stop_hz, self.step_hz = start_hz, stop_hz, step_hz
        self.mode = "range"

    def lockout(self, hz: float) -> None:
        self.lockouts.add(hz)

    def unlock(self, hz: float) -> None:
        self.lockouts.discard(hz)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            raise ScanError("already running")
        self._stop.clear()
        self._paused.clear()
        self.stats = ScanStats()
        self._thread = threading.Thread(target=self._run, name="bosun-scan", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._paused.set()

    def resume_scan(self) -> None:
        self._paused.clear()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def run(self) -> None:
        self._run()

    def _targets(self):
        if self.mode == "list":
            if self.bank is None:
                raise ScanError("list scan needs a bank")
            return [m.frequency for m in self.bank.scan_order()]
        count = int((self.stop_hz - self.start_hz) // self.step_hz) + 1
        return [self.start_hz + i * self.step_hz for i in range(count)]

    def _run(self) -> None:
        while not self._stop.is_set():
            for hz in self._targets():
                if self._stop.is_set():
                    return
                if hz in self.lockouts:
                    continue
                try:
                    self.radio.set_frequency(hz)
                except Exception:
                    self.stats.errors += 1
                    continue
                self.stats.steps += 1
                if self.on_step:
                    self.on_step(hz)
                self._wait(self.dwell)
                if self._stop.is_set():
                    return
                if self.detector is not None and self.detector():
                    self.stats.hits += 1
                    if self.on_hit:
                        self.on_hit(hz)
                    if self.resume == "stop":
                        self._stop.set()
                        return
                    if self.resume == "time":
                        self._wait(self.resume_after)
            self.stats.cycles += 1
            if self.max_cycles and self.stats.cycles >= self.max_cycles:
                return

    def _wait(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return
            while self._paused.is_set() and not self._stop.is_set():
                time.sleep(0.02)
            time.sleep(0.01)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())
