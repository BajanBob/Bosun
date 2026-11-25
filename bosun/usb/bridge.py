"""Known USB-serial bridge IDs for deterministic binding."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import TransportError

CP210X = [(0x10C4, 0xEA60), (0x10C4, 0xEA70), (0x10C4, 0xEA71)]
FTDI = [(0x0403, 0x6001), (0x0403, 0x6015), (0x0403, 0x6010)]
SILABS_CDC = [(0x10C4, 0xEA80)]
ALL_BRIDGES = CP210X + FTDI + SILABS_CDC


@dataclass(frozen=True)
class Bridge:
    device: str
    vid: int
    pid: int
    serial: str
    description: str

    @property
    def identity(self) -> tuple[int, int]:
        return (self.vid, self.pid)


def enumerate_bridges() -> list[Bridge]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise TransportError("pyserial not installed") from exc
    out = []
    for p in list_ports.comports():
        if p.vid is None or p.pid is None:
            continue
        if (p.vid, p.pid) in ALL_BRIDGES:
            out.append(Bridge(p.device, p.vid, p.pid, p.serial or "", p.description or ""))
    return sorted(out, key=lambda b: b.device)


def find_bridge(identity: tuple[int, int], *, serial: str | None = None):
    for b in enumerate_bridges():
        if b.identity == identity and (serial is None or b.serial == serial):
            return b
    return None
