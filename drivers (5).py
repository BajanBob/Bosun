"""Concrete drivers. Frame shapes documented in docs/PROTOCOLS.md."""

from __future__ import annotations

import re

from ..caps import Cap
from ..errors import ProtocolError
from ..memory import Memory
from ..spectrum import parse_burst, scope_mode_code
from .base import RadioBase
from .protocols import AorCodec, AsciiCatCodec, CivCodec, bcd_decode, bcd_encode

CIV_FREQ = b"\x00"
CIV_MODE = b"\x01"
CIV_READ_FREQ = b"\x03"
CIV_READ_MODE = b"\x04"
CIV_VFO = b"\x07"
CIV_MEM_WRITE = b"\x09"
CIV_MEM_READ = b"\x0a"
CIV_ATT = b"\x11"
CIV_LEVEL = b"\x14"
CIV_METER = b"\x15"
CIV_PREAMP = b"\x16"
CIV_SET = b"\x1a"
CIV_PTT = b"\x1c"
CIV_SCOPE = b"\x27"

CIV_MODES = {
    "LSB": 0x00, "USB": 0x01, "AM": 0x02, "CW": 0x03, "RTTY": 0x04,
    "FM": 0x05, "WFM": 0x06, "CW-R": 0x07, "RTTY-R": 0x08,
    "DV": 0x17, "DD": 0x22,
}
CIV_FILTERS = {"FIL1": 0x01, "FIL2": 0x02, "FIL3": 0x03}
CIV_AGC = {"OFF": 0x00, "FAST": 0x01, "MID": 0x02, "SLOW": 0x03}
CIV_VFO_SEL = {"A": 0x00, "B": 0x01}
_MODE_REPLY = re.compile(rb"MD\s*([0-9])")


def _pct(pct: float) -> int:
    return max(0, min(255, round(float(pct) * 2.55)))


def _label(label: str) -> bytes:
    return label.encode("ascii", "replace").ljust(9, b"\xff")


class IcomBase(RadioBase):
    vendor = "Icom"
    transport_kind = "usb-serial"
    default_baud = 19200
    bridge_ids = [(0x10C4, 0xEA70), (0x10C4, 0xEA60)]
    audio_format = (48000, 1, "int16")
    modes = CIV_MODES

    def __init__(self, transport, addr: int, **kw) -> None:
        super().__init__(transport, CivCodec(addr), **kw)
        self.addr = addr

    def _do_set_frequency(self, hz: float) -> None:
        self._send(CIV_FREQ, bcd_encode(int(round(hz)), 5))

    def _do_get_frequency(self) -> float:
        return float(bcd_decode(self._query(CIV_READ_FREQ)[0][1:6]))

    def _do_set_mode(self, code: int) -> None:
        self._send(CIV_MODE, bytes([code, 0x01]))

    def _do_get_mode(self) -> int:
        return self._query(CIV_READ_MODE)[0][1]

    def _do_ptt(self, on: bool) -> None:
        self._send(CIV_PTT, b"\x00" + bytes([1 if on else 0]))

    def _do_vfo_select(self, which: str) -> None:
        self._send(CIV_VFO, bytes([CIV_VFO_SEL[which]]))

    def _do_vfo_swap(self) -> None:
        self._send(CIV_VFO, b"\x03")

    def _do_vfo_copy(self) -> None:
        self._send(CIV_VFO, b"\x02")

    def _do_memory_write(self, mem: Memory) -> None:
        self._send(CIV_MEM_WRITE, (
            bcd_encode(mem.channel, 2)[::-1]
            + bcd_encode(int(round(mem.frequency)), 5)
            + bytes([self._check_mode(mem.mode), 0x01, 0x00])
            + b"\xff\xff\xff" + _label(mem.label)
        ))

    def _mode_name(self, code: int) -> str:
        for name, val in self.modes.items():
            if val == code:
                return name
        raise ProtocolError(f"{self.model}: unknown mode code {code}")

    def _do_memory_read(self, channel: int) -> Memory:
        body = self._query(CIV_MEM_READ, bcd_encode(channel, 2) + b"\x01")[0]
        if len(body) < 9:
            raise ProtocolError(f"{self.model}: short memory reply")
        label = body[12:21].rstrip(b"\xff").decode("ascii", "replace")
        return Memory(channel, float(bcd_decode(body[3:8])), self._mode_name(body[8]), label)

    def _do_memory_clear(self, channel: int) -> None:
        self._send(CIV_MEM_READ, bcd_encode(channel, 2) + b"\x00")

    def _do_squelch_open(self):
        reply = self._query(CIV_METER, b"\x03")[0]
        return len(reply) > 2 and reply[2] != 0x00

    def set_filter(self, name: str) -> None:
        self.require(Cap.FILTER)
        if name.upper() not in CIV_FILTERS:
            raise ProtocolError(f"unknown filter {name!r}")
        self._send(CIV_SET, b"\x05" + bytes([CIV_FILTERS[name.upper()]]))

    def set_agc(self, name: str) -> None:
        self.require(Cap.AGC)
        if name.upper() not in CIV_AGC:
            raise ProtocolError(f"unknown AGC {name!r}")
        self._send(CIV_SET, b"\x03" + bytes([CIV_AGC[name.upper()]]))

    def _level(self, sub: int, value: int) -> None:
        self._send(CIV_LEVEL, bytes([sub]) + bcd_encode(max(0, min(255, value)), 2))

    def set_af_gain(self, pct: float) -> None:
        self.require(Cap.AF_GAIN)
        self._level(0x01, _pct(pct))

    def set_rf_gain(self, pct: float) -> None:
        self.require(Cap.RF_GAIN)
        self._level(0x02, _pct(pct))

    def set_squelch(self, pct: float) -> None:
        self.require(Cap.SQUELCH)
        self._level(0x03, _pct(pct))

    def set_attenuator(self, on: bool) -> None:
        self.require(Cap.ATTENUATOR)
        self._send(CIV_ATT, bytes([1 if on else 0]))

    def set_preamp(self, on: bool) -> None:
        self.require(Cap.PREAMP)
        self._send(CIV_PREAMP, b"\x02" + bytes([1 if on else 0]))


class IC9100(IcomBase):
    model = "IC-9100"
    caps = (
        Cap.RX | Cap.TX | Cap.TUNE | Cap.MODE | Cap.FILTER | Cap.AGC
        | Cap.SQUELCH | Cap.ATTENUATOR | Cap.PREAMP | Cap.RF_GAIN
        | Cap.AF_GAIN | Cap.PTT | Cap.VFO | Cap.MEMORY | Cap.SCAN
        | Cap.USB_AUDIO | Cap.USB_SERIAL
    )
    bands = [(0.03e6, 60e6), (118e6, 174e6), (420e6, 450e6)]

    def __init__(self, transport, **kw) -> None:
        super().__init__(transport, addr=0x7C, **kw)


class IC9700(IcomBase):
    model = "IC-9700"
    caps = (
        Cap.RX | Cap.TX | Cap.TUNE | Cap.MODE | Cap.FILTER | Cap.AGC
        | Cap.SQUELCH | Cap.ATTENUATOR | Cap.PREAMP | Cap.RF_GAIN
        | Cap.AF_GAIN | Cap.PTT | Cap.VFO | Cap.MEMORY | Cap.SCAN
        | Cap.USB_AUDIO | Cap.USB_SERIAL | Cap.DV | Cap.SPECTRUM
    )
    bands = [(144e6, 148e6), (430e6, 450e6), (1240e6, 1300e6)]

    def __init__(self, transport, **kw) -> None:
        super().__init__(transport, addr=0xA2, **kw)

    def set_scope(self, mode: str = "center", on: bool = True) -> None:
        self.require(Cap.SPECTRUM)
        self._send(CIV_SCOPE, b"\x10" + bytes([scope_mode_code(mode) if on else 0x00]))

    def _do_scope_read(self, *, center_hz: float, span_hz: float):
        self._send(CIV_SCOPE, b"\x11\x02")
        frames, buffer = [], b""
        for _ in range(48):
            chunk = self._t.read(512, self._timeout)
            if not chunk:
                if frames:
                    break
                continue
            got, buffer = self._codec.split(buffer + chunk)
            frames.extend(f for f in got if len(f) >= 3 and f[:2] == b"\x27\x00")
        return parse_burst(frames, center_hz=center_hz, span_hz=span_hz)


class FT991A(RadioBase):
    model = "FT-991A"
    vendor = "Yaesu"
    caps = (
        Cap.RX | Cap.TX | Cap.TUNE | Cap.MODE | Cap.FILTER | Cap.AGC
        | Cap.SQUELCH | Cap.ATTENUATOR | Cap.PREAMP | Cap.RF_GAIN
        | Cap.AF_GAIN | Cap.PTT | Cap.VFO | Cap.MEMORY | Cap.SCAN
        | Cap.USB_AUDIO | Cap.USB_SERIAL
    )
    transport_kind = "usb-serial"
    default_baud = 38400
    bridge_ids = [(0x10C4, 0xEA70), (0x0403, 0x6001)]
    audio_format = (48000, 1, "int16")
    modes = {
        "LSB": "1", "USB": "2", "CW": "3", "FM": "4", "AM": "5",
        "RTTY-L": "6", "CW-R": "7", "DATA-L": "8", "RTTY-U": "9",
        "DATA-FM": "A", "FM-N": "B", "DATA-U": "C",
    }
    bands = [(0.03e6, 56e6), (118e6, 164e6), (420e6, 450e6)]

    def __init__(self, transport, **kw) -> None:
        super().__init__(transport, AsciiCatCodec(), **kw)

    @staticmethod
    def _pad(value: int, width: int) -> bytes:
        text = str(int(value)).zfill(width)
        if len(text) != width:
            raise ProtocolError(f"value overflows {width} digits")
        return text.encode()

    def _do_set_frequency(self, hz: float) -> None:
        self._send(b"FA", self._pad(round(hz), 9))

    def _do_get_frequency(self) -> float:
        return float(self._query(b"FA")[0][2:11])

    def _do_set_mode(self, code) -> None:
        self._send(b"MD", code.encode())

    def _do_get_mode(self):
        return self._query(b"MD")[0][2:3].decode()

    def _do_ptt(self, on: bool) -> None:
        self._send(b"TX", b"1" if on else b"0")

    def _do_vfo_select(self, which: str) -> None:
        self._send(b"VS", b"0" if which == "A" else b"1")

    def _do_vfo_swap(self) -> None:
        self._send(b"SV")

    def _do_vfo_copy(self) -> None:
        self._send(b"BA")

    def _do_memory_write(self, mem: Memory) -> None:
        self._send(
            b"MW" + self._pad(mem.channel, 3),
            self._pad(round(mem.frequency), 9) + b"00000"
            + mem.mode.upper().encode()[:1] + b"0000",
        )

    def _mode_name(self, code: str) -> str:
        for name, val in self.modes.items():
            if val == code:
                return name
        raise ProtocolError(f"{self.model}: unknown mode code {code!r}")

    def _do_memory_read(self, channel: int) -> Memory:
        body = self._query(b"MR" + self._pad(channel, 3))[0]
        if len(body) < 20:
            raise ProtocolError(f"{self.model}: short memory reply")
        return Memory(channel, float(body[5:14]), self._mode_name(body[19:20].decode()))

    def _do_memory_clear(self, channel: int) -> None:
        self._send(b"MC" + self._pad(channel, 3))

    def _do_squelch_open(self):
        body = self._query(b"IF")[0]
        return len(body) > 20 and body[20:21] == b"1"

    def set_af_gain(self, pct: float) -> None:
        self.require(Cap.AF_GAIN)
        self._send(b"AG0", self._pad(_pct(pct), 3))

    def set_rf_gain(self, pct: float) -> None:
        self.require(Cap.RF_GAIN)
        self._send(b"RG0", self._pad(_pct(pct), 3))

    def set_squelch(self, pct: float) -> None:
        self.require(Cap.SQUELCH)
        self._send(b"SQ0", self._pad(_pct(pct), 3))

    def set_filter(self, width: int) -> None:
        self.require(Cap.FILTER)
        self._send(b"SH0", self._pad(max(0, min(21, int(width))), 2))

    def set_agc(self, speed: int) -> None:
        self.require(Cap.AGC)
        self._send(b"GT0", self._pad(max(0, min(11, int(speed))), 2))

    def set_attenuator(self, on: bool) -> None:
        self.require(Cap.ATTENUATOR)
        self._send(b"RA0", b"1" if on else b"0")

    def set_preamp(self, on: bool) -> None:
        self.require(Cap.PREAMP)
        self._send(b"PA0", b"0" if on else b"1")


class AorBase(RadioBase):
    """AOR receivers: receive only, no VFO pair, no PTT."""

    vendor = "AOR"
    caps = (
        Cap.RX | Cap.TUNE | Cap.MODE | Cap.FILTER | Cap.AGC
        | Cap.SQUELCH | Cap.ATTENUATOR | Cap.AF_GAIN | Cap.MEMORY | Cap.SCAN
    )
    transport_kind = "usb-serial"
    default_baud = 9600
    bridge_ids = [(0x0403, 0x6001), (0x10C4, 0xEA60)]
    modes = {"WFM": 0, "NFM": 1, "AM": 2, "USB": 3, "LSB": 4, "CW": 5}

    def __init__(self, transport, **kw) -> None:
        super().__init__(transport, AorCodec(), **kw)

    def _do_set_frequency(self, hz: float) -> None:
        self._send(b"RF", str(int(round(hz))).zfill(10).encode())

    def _do_get_frequency(self) -> float:
        reply = self._query(b"RF")[0]
        digits = re.sub(rb"[^0-9]", b"", reply)[:10]
        if not digits:
            raise ProtocolError(f"{self.model}: unparsable reply {reply!r}")
        return float(digits)

    def _do_set_mode(self, code: int) -> None:
        self._send(b"MD", str(code).encode())

    def _do_get_mode(self) -> int:
        match = _MODE_REPLY.search(self._query(b"MD")[0])
        if match is None:
            raise ProtocolError(f"{self.model}: unparsable mode reply")
        return int(match.group(1))

    def ptt(self, on: bool) -> None:
        # Distinguish a known receive-only hardware limitation from a generic
        # missing capability so callers can handle this driver explicitly.
        raise NotImplementedError("AOR receivers have no PTT")

    def _do_ptt(self, on: bool) -> None:
        raise NotImplementedError("AOR receivers have no PTT")

    def _do_memory_write(self, mem: Memory) -> None:
        self._send(b"MW", (
            f"{mem.channel:02d}".encode()
            + str(int(round(mem.frequency))).zfill(10).encode()
            + str(self._check_mode(mem.mode)).encode()
        ))

    def _mode_name(self, code: int) -> str:
        for name, val in self.modes.items():
            if val == code:
                return name
        raise ProtocolError(f"{self.model}: unknown mode code {code}")

    def _do_memory_read(self, channel: int) -> Memory:
        reply = self._query(b"MR" + f"{channel:02d}".encode())[0]
        digits = re.sub(rb"[^0-9]", b"", reply)
        if len(digits) < 12:
            raise ProtocolError(f"{self.model}: unparsable memory reply {reply!r}")
        return Memory(channel, float(digits[:10]), self._mode_name(int(chr(digits[11]))))

    def _do_memory_clear(self, channel: int) -> None:
        self._send(b"MC", f"{channel:02d}".encode())

    def set_squelch(self, pct: float) -> None:
        self.require(Cap.SQUELCH)
        self._send(b"SQ", str(_pct(pct)).zfill(3).encode())

    def set_attenuator(self, on: bool) -> None:
        self.require(Cap.ATTENUATOR)
        self._send(b"AT", b"1" if on else b"0")

    def set_af_gain(self, pct: float) -> None:
        self.require(Cap.AF_GAIN)
        self._send(b"AG", str(_pct(pct)).zfill(3).encode())


class AR8200(AorBase):
    model = "AR-8200"
    caps = AorBase.caps & ~Cap.SQUELCH
    bands = [(0.5e6, 2040e6)]


class AR8600(AorBase):
    model = "AR-8600"
    bands = [(0.1e6, 3000e6)]
