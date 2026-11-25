import pytest

from bosun.errors import MemoryError_, OutOfRange, ProtocolError, UnsupportedCapability
from bosun.memory import Memory
from bosun.radios.drivers import AR8200, AR8600, FT991A, IC9100, IC9700
from bosun.radios.protocols import (
    AorCodec,
    AsciiCatCodec,
    CivCodec,
    bcd_decode,
    bcd_encode,
)
from bosun.transport import NullTransport


def test_bcd_roundtrip():
    assert bcd_encode(145000000, 5) == b"\x00\x00\x00\x45\x01"
    assert bcd_decode(b"\x00\x00\x00\x45\x01") == 145000000


def test_bcd_overflow():
    with pytest.raises(ProtocolError):
        bcd_encode(1450000000, 5)


def test_civ_frame_shape():
    codec = CivCodec(0x7C)
    assert codec.frame(b"\x00", bcd_encode(145000000, 5)) == (
        b"\xfe\xfe\x7c\x00\x00\x00\x00\x45\x01\xfd")


def test_civ_split_drops_own_echo():
    codec = CivCodec(0x7C)
    buf = b"\xfe\xfe\xe0\x03\x00\xfd\xfe\xfe\x7c\x03\x00\x00\x50\x14\x00\xfd"
    frames, rest = codec.split(buf)
    assert frames == [b"\x03\x00\x00\x50\x14\x00"]
    assert rest == b""


def test_cat_allows_variable_length():
    codec = AsciiCatCodec()
    assert codec.frame(b"FA", b"014225000") == b"FA014225000;"
    with pytest.raises(ProtocolError):
        codec.frame(b"F", b"014225000")


def test_aor_terminator():
    assert AorCodec().frame(b"RF", b"0121500000") == b"RF0121500000\r"


def test_null_transport_loopback():
    t = NullTransport(responder=lambda d: b"echo")
    t.open()
    t.write(b"x")
    assert t.read(4) == b"echo"


def test_icom_set_frequency():
    t = NullTransport(responder=lambda d: b"")
    radio = IC9700(t)
    radio.connect()
    radio.set_frequency(144_300_000)
    assert t.written == b"\xfe\xfe\xa2\x00\x00\x00\x30\x44\x01\xfd"


def test_icom_band_limit():
    with pytest.raises(OutOfRange):
        IC9700(NullTransport()).set_frequency(14_000_000)


def test_aor_receive_only():
    with pytest.raises(NotImplementedError):
        AR8600(NullTransport()).ptt(True)


def test_ar8200_has_no_squelch():
    with pytest.raises(UnsupportedCapability):
        AR8200(NullTransport()).set_squelch(10)


def test_ft991a_frequency_padding():
    t = NullTransport(responder=lambda d: b"")
    radio = FT991A(t)
    radio.connect()
    radio.set_frequency(14_225_000)
    assert t.written == b"FA014225000;"


def test_icom_vfo_select():
    t = NullTransport(responder=lambda d: b"")
    IC9100(t).vfo_select("B")
    assert t.written == b"\xfe\xfe\x7c\x07\x01\xfd"


def test_aor_has_no_vfo():
    with pytest.raises(UnsupportedCapability):
        AR8600(NullTransport()).vfo_select("A")


def test_icom_memory_write_payload():
    t = NullTransport(responder=lambda d: b"")
    IC9100(t).memory_write(Memory(7, 14_225_000, "USB", "CALL"))
    assert t.written.startswith(b"\xfe\xfe\x7c\x09\x00\x07")
    assert b"CALL" in t.written
    assert t.written.endswith(b"\xfd")


def test_label_too_long():
    with pytest.raises(MemoryError_):
        Memory(1, 14_000_000, "USB", "TOOLONG10").validate()
