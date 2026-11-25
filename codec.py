"""USB audio codec control. Radios expect 48 kHz / 16-bit / mono."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..errors import CodecError

NATIVE_RATE = 48_000
NATIVE_WIDTH = "int16"
NATIVE_CHANNELS = 1


@dataclass(frozen=True)
class CodecProfile:
    name: str
    match: str
    rate: int = NATIVE_RATE
    channels: int = NATIVE_CHANNELS
    dtype: str = NATIVE_WIDTH

    def matches(self, device_name: str) -> bool:
        return self.match.lower() in device_name.lower()


PROFILES = [
    CodecProfile("icom-usb-audio", "usb audio codec"),
    CodecProfile("icom-9700", "icom"),
    CodecProfile("yaesu-991a", "yaesu"),
    CodecProfile("generic-48k", "codec"),
]


def list_codecs() -> list[str]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise CodecError("sounddevice not installed") from exc
    return [
        d["name"] for d in sd.query_devices()
        if d["max_input_channels"] > 0 or d["max_output_channels"] > 0
    ]


def resolve(name: str) -> tuple[int, CodecProfile]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise CodecError("sounddevice not installed") from exc
    for idx, dev in enumerate(sd.query_devices()):
        if name.lower() in dev["name"].lower():
            for prof in PROFILES:
                if prof.matches(dev["name"]):
                    return idx, prof
            return idx, PROFILES[-1]
    raise CodecError(f"no audio device matching {name!r}")


class USBCodec:
    """Full-duplex wrapper with overrun accounting."""

    def __init__(self, name: str, *, blocksize: int = 480) -> None:
        self.name, self.blocksize = name, blocksize
        self.index = None
        self.profile = None
        self._in = self._out = None
        self._lock = threading.Lock()
        self.frames_in = self.frames_out = 0
        self.overruns = self.underruns = 0

    def open(self) -> None:
        import sounddevice as sd

        self.index, self.profile = resolve(self.name)
        try:
            self._in = sd.InputStream(
                device=self.index, samplerate=self.profile.rate,
                channels=self.profile.channels, dtype=self.profile.dtype,
                blocksize=self.blocksize,
            )
            self._out = sd.OutputStream(
                device=self.index, samplerate=self.profile.rate,
                channels=self.profile.channels, dtype=self.profile.dtype,
                blocksize=self.blocksize,
            )
            self._in.start()
            self._out.start()
        except Exception as exc:
            self.close()
            raise CodecError(f"cannot open codec {self.name!r}: {exc}") from exc

    def close(self) -> None:
        for stream in (self._in, self._out):
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
        self._in = self._out = None

    def read(self):
        if self._in is None:
            raise CodecError("codec not open")
        with self._lock:
            data, overflowed = self._in.read(self.blocksize)
        if overflowed:
            self.overruns += 1
        self.frames_in += len(data)
        return data

    def write(self, block) -> None:
        if self._out is None:
            raise CodecError("codec not open")
        with self._lock:
            self._out.write(block)
        self.frames_out += len(block)

    @property
    def latency(self) -> float:
        return 0.0 if self._in is None else float(self._in.latency)

    def stats(self) -> dict:
        return {
            "device": self.name,
            "frames_in": self.frames_in,
            "frames_out": self.frames_out,
            "overruns": self.overruns,
            "underruns": self.underruns,
            "latency_s": round(self.latency, 4),
        }
