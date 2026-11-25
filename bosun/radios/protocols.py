"""Wire protocols: CI-V, Yaesu/Kenwood ASCII CAT, AOR, configurable ASCII."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..errors import ProtocolError

CIV_PREAMBLE = b"\xfe\xfe"
CIV_EOFRAME = b"\xfd"


def bcd_encode(value: int, nbytes: int) -> bytes:
    if value < 0:
        raise ProtocolError("negative value")
    if nbytes < 0:
        raise ProtocolError("BCD byte count must not be negative")
    # CI-V frequency fields use two packed decimal digits per byte, least
    # significant pair first. Reject values that exceed the field width.
    if value >= 10 ** (2 * nbytes - 1):
        raise ProtocolError("value overflows BCD field")
    out = bytearray()
    for _ in range(nbytes):
        pair, value = value % 100, value // 100
        out.append(((pair // 10) << 4) | (pair % 10))
    if value:
        raise ProtocolError("value overflows BCD field")
    return bytes(out)


def bcd_decode(data: bytes) -> int:
    value = 0
    for i, byte in enumerate(data):
        hi, lo = byte >> 4, byte & 0x0F
        if hi > 9 or lo > 9:
            raise ProtocolError(f"bad BCD byte 0x{byte:02x}")
        value += (hi * 10 + lo) * (100 ** i)
    return value


class Codec(ABC):
    @abstractmethod
    def frame(self, cmd: bytes, payload: bytes = b"") -> bytes: ...

    @abstractmethod
    def split(self, buffer: bytes) -> tuple[list[bytes], bytes]: ...


class CivCodec(Codec):
    """Icom CI-V, addressed, FD-terminated."""

    def __init__(self, radio_addr: int, controller_addr: int = 0xE0) -> None:
        self.radio_addr, self.controller_addr = radio_addr, controller_addr

    def frame(self, cmd: bytes, payload: bytes = b"") -> bytes:
        return CIV_PREAMBLE + bytes([self.radio_addr]) + cmd + payload + CIV_EOFRAME

    def split(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        frames = []
        while True:
            start = buffer.find(CIV_PREAMBLE)
            if start < 0:
                return frames, buffer[-1:]
            end = buffer.find(CIV_EOFRAME, start + 2)
            if end < 0:
                return frames, buffer[start:]
            body = buffer[start + 2 : end]
            buffer = buffer[end + 1 :]
            # Replies normally carry destination (controller) then source
            # (radio). Some adapters omit the destination and expose only the
            # radio address. Drop controller-only echoes and unrelated frames.
            if len(body) >= 3 and body[0] == self.controller_addr and body[1] == self.radio_addr:
                frames.append(body[2:])
            elif len(body) >= 2 and body[0] == self.radio_addr:
                frames.append(body[1:])


class AsciiCatCodec(Codec):
    """Yaesu / Kenwood ASCII CAT: two-letter command, parameters, ';' terminator.

    Commands vary in length ("FA;" reads, "FA014250000;" sets), so only the
    two-letter command is enforced.
    """

    TERM = b";"

    def frame(self, cmd: bytes, payload: bytes = b"") -> bytes:
        if len(cmd) < 2 or not cmd[:2].isalpha():
            raise ProtocolError("CAT frame requires a two-letter command")
        return cmd + payload + self.TERM

    def split(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        frames = []
        while self.TERM in buffer:
            body, buffer = buffer.split(self.TERM, 1)
            body = body.strip()
            # "?" is the radio's "command not understood" reply.
            if len(body) >= 2 and body[:2].isalpha():
                frames.append(body)
        return frames, buffer


class AorCodec(Codec):
    """AOR ASCII, CR-terminated, unaddressed."""

    TERM = b"\r"

    def frame(self, cmd: bytes, payload: bytes = b"") -> bytes:
        return cmd + payload + self.TERM

    def split(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        frames = []
        while self.TERM in buffer:
            body, buffer = buffer.split(self.TERM, 1)
            if body.strip():
                frames.append(body.strip())
        return frames, buffer


class LineCodec(Codec):
    """Generic ASCII line protocol with a configurable terminator."""

    def __init__(self, terminator: bytes = b"\r") -> None:
        self.TERM = terminator or b"\r"

    def frame(self, cmd: bytes, payload: bytes = b"") -> bytes:
        return cmd + payload + self.TERM

    def split(self, buffer: bytes) -> tuple[list[bytes], bytes]:
        frames = []
        while self.TERM in buffer:
            body, buffer = buffer.split(self.TERM, 1)
            if body.strip():
                frames.append(body.strip())
        return frames, buffer
