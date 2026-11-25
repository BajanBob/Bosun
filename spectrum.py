"""Band scope parsing. Icom 11-bit bins, two per three bytes."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ProtocolError


@dataclass
class ScopeFrame:
    start_hz: float
    bin_hz: float
    levels: list[int] = field(default_factory=list)

    @property
    def stop_hz(self) -> float:
        return self.start_hz + self.bin_hz * len(self.levels)

    def peak(self) -> tuple[float, int]:
        if not self.levels:
            raise ProtocolError("empty frame")
        idx = max(range(len(self.levels)), key=self.levels.__getitem__)
        return (self.start_hz + idx * self.bin_hz, self.levels[idx])


def unpack_bins(payload: bytes) -> list[int]:
    out: list[int] = []
    i, n = 0, len(payload)
    while i + 2 < n:
        out.append(payload[i] | ((payload[i + 1] & 0x03) << 8))
        out.append((payload[i + 1] >> 2) | ((payload[i + 2] & 0x0F) << 6))
        i += 3
    return out


def parse_burst(frames, *, center_hz: float, span_hz: float) -> ScopeFrame:
    ordered = []
    for body in frames:
        if len(body) >= 4 and body[:2] == b"\x27\x00":
            ordered.append((body[2], body[3:]))
    if not ordered:
        raise ProtocolError("no scope frames")
    ordered.sort(key=lambda pair: pair[0])
    levels: list[int] = []
    for _, payload in ordered:
        levels.extend(unpack_bins(payload))
    if not levels:
        raise ProtocolError("burst carried no bins")
    bin_hz = span_hz / len(levels)
    return ScopeFrame(center_hz - span_hz / 2, bin_hz, levels)


def scope_mode_code(mode: str) -> int:
    codes = {"center": 0x00, "fixed": 0x01, "scroll": 0x02}
    try:
        return codes[mode.lower()]
    except KeyError:
        raise ProtocolError(f"unknown scope mode {mode!r}") from None
