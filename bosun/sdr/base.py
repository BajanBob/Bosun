"""SDR backend contract. Backends yield complex64 blocks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SDRCaps:
    min_hz: float = 0.0
    max_hz: float = 0.0
    max_rate: float = 0.0
    gain_range: tuple[float, float] = (0.0, 0.0)
    antennas: list[str] = field(default_factory=list)
    bias_tee: bool = False

    def covers(self, hz: float) -> bool:
        return self.min_hz <= hz <= self.max_hz


class SDRBackend(ABC):
    name = "abstract"
    driver_key = "abstract"

    @classmethod
    @abstractmethod
    def probe(cls) -> list[str]: ...

    @abstractmethod
    def open(self, device: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def caps(self) -> SDRCaps: ...

    @abstractmethod
    def set_frequency(self, hz: float) -> None: ...

    @abstractmethod
    def set_sample_rate(self, rate: float) -> None: ...

    @abstractmethod
    def set_gain(self, db: float, element: str | None = None) -> None: ...

    @abstractmethod
    def set_bandwidth(self, hz: float) -> None: ...

    @abstractmethod
    def stream(self, nsamples: int): ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
