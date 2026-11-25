"""Memory channels and JSON banks. Radio sync is explicit, never implicit."""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass, field

from .errors import MemoryError_


@dataclass
class Memory:
    channel: int
    frequency: float
    mode: str
    label: str = ""
    skip: bool = False

    def validate(self, *, max_channel: int = 99, modes: set[str] | None = None) -> None:
        if not 0 <= self.channel <= max_channel:
            raise MemoryError_(f"channel {self.channel} outside 0..{max_channel}")
        if self.frequency <= 0:
            raise MemoryError_("frequency must be positive")
        if modes is not None and self.mode.upper() not in modes:
            raise MemoryError_(f"mode {self.mode!r} unavailable")
        if len(self.label) > 8:
            raise MemoryError_("label longer than 8 characters")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Memory":
        try:
            return cls(
                channel=int(data["channel"]),
                frequency=float(data["frequency"]),
                mode=str(data["mode"]),
                label=str(data.get("label", ""))[:9],
                skip=bool(data.get("skip", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MemoryError_(f"malformed record: {exc}") from exc


@dataclass
class MemoryBank:
    model: str
    path: pathlib.Path
    max_channel: int = 99
    modes: set[str] = field(default_factory=set)
    channels: dict[int, Memory] = field(default_factory=dict)

    @classmethod
    def open(cls, model: str, path, **kw) -> "MemoryBank":
        bank = cls(model=model, path=pathlib.Path(path), **kw)
        bank.load()
        return bank

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MemoryError_(f"cannot read {self.path}: {exc}") from exc
        self.channels = {}
        for record in data.get("channels", []):
            mem = Memory.from_dict(record)
            mem.validate(max_channel=self.max_channel, modes=self.modes or None)
            self.channels[mem.channel] = mem

    def save(self) -> None:
        payload = {
            "model": self.model,
            "channels": [m.to_dict() for _, m in sorted(self.channels.items())],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            raise MemoryError_(f"cannot write {self.path}: {exc}") from exc

    def put(self, mem: Memory) -> None:
        mem.validate(max_channel=self.max_channel, modes=self.modes or None)
        self.channels[mem.channel] = mem

    def get(self, channel: int) -> Memory:
        try:
            return self.channels[channel]
        except KeyError:
            raise MemoryError_(f"channel {channel} empty") from None

    def drop(self, channel: int) -> None:
        if channel not in self.channels:
            raise MemoryError_(f"channel {channel} empty")
        del self.channels[channel]

    def clear(self) -> None:
        self.channels.clear()

    def scan_order(self) -> list[Memory]:
        return [m for _, m in sorted(self.channels.items()) if not m.skip]

    def duplicates(self) -> list[tuple[int, int]]:
        seen: dict[float, int] = {}
        out = []
        for ch, mem in sorted(self.channels.items()):
            if mem.frequency in seen:
                out.append((seen[mem.frequency], ch))
            else:
                seen[mem.frequency] = ch
        return out

    def __len__(self) -> int:
        return len(self.channels)


def push_bank(radio, bank: MemoryBank) -> int:
    count = 0
    for mem in bank.channels.values():
        radio.memory_write(mem)
        count += 1
    return count


def pull_bank(radio, bank: MemoryBank, channels) -> int:
    count = 0
    for ch in channels:
        bank.put(radio.memory_read(ch))
        count += 1
    return count
