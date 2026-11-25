import pytest

from bosun.errors import ProtocolError
from bosun.spectrum import parse_burst, scope_mode_code, unpack_bins


def test_unpack_pairs():
    out = unpack_bins(bytes([0x01, 0x00 | ((0xFF << 2) & 0xFF), 0xFF & 0x0F]))
    assert out[0] == 0x001
    assert out[1] == 0x3FF


def test_parse_orders_by_sequence():
    frames = [b"\x27\x00\x01" + b"\x10\x00\x00", b"\x27\x00\x00" + b"\x20\x00\x00"]
    frame = parse_burst(frames, center_hz=145_000_000, span_hz=1_000_000)
    assert frame.levels[0] == 0x020
    assert frame.start_hz == 144_500_000


def test_empty_burst():
    with pytest.raises(ProtocolError):
        parse_burst([], center_hz=100e6, span_hz=1e6)


def test_peak():
    frames = [b"\x27\x00\x00" + bytes([0x00, 0x00, 0x00, 0xFF, 0x03, 0x00])]
    _, level = parse_burst(frames, center_hz=0.0, span_hz=3.0).peak()
    assert level == 0x3FF


def test_mode_code():
    assert scope_mode_code("center") == 0
    with pytest.raises(ProtocolError):
        scope_mode_code("bogus")
