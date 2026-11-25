import json

import pytest

from bosun.errors import BosunError, ConfigError
from bosun.radios import registry
from bosun.radios.drivers import FT991A, IC7300, ICR8600, TS590SG, RadtelRT950Pro
from bosun.radios.profile import make_driver
from bosun.radios.protocols import AsciiCatCodec
from bosun.transport import NullTransport


def replies(table):
    return NullTransport(responder=lambda d: table.get(bytes(d), b""))


def test_cat_codec_accepts_short_commands():
    c = AsciiCatCodec()
    assert c.frame(b"FA") == b"FA;"
    assert c.split(b"MD02;FA014250000;?;")[0] == [b"MD02", b"FA014250000"]


def test_yaesu_reads_frequency_and_mode():
    r = FT991A(replies({b"FA;": b"FA014250000;", b"MD0;": b"MD02;"}))
    r.connect()
    r.set_mode("USB")
    assert r.get_frequency() == 14_250_000 and r.get_mode() == "USB"
    assert r._t.written.startswith(b"MD02;")


def test_kenwood_round_trip_and_busy():
    r = TS590SG(replies({b"FA;": b"FA00007100000;", b"MD;": b"MD1;", b"BY;": b"BY10;"}))
    r.connect()
    r.set_frequency(7_100_000)
    assert r._t.written == b"FA00007100000;"
    assert r.get_frequency() == 7_100_000 and r.get_mode() == "LSB"
    assert r.squelch_open() is True


def test_icom_addresses():
    t = NullTransport()
    IC7300(t).set_frequency(7_100_000)
    assert t.written == b"\xfe\xfe\x94\x00\x00\x00\x10\x07\x00\xfd"
    t = NullTransport()
    ICR8600(t).set_frequency(121_500_000)
    assert t.written[2] == 0x96


def test_registry_has_every_maker():
    v = registry.vendors()
    for maker in ("Icom", "Yaesu", "Kenwood", "AOR", "Barrett", "Harris", "Radtel"):
        assert v.get(maker), maker


def test_radtel_is_audio_only():
    r = RadtelRT950Pro()
    assert r.status()["note"].startswith("No computer control")
    assert "record" in registry.describe("RT-950 Pro").lower()


def test_unconfigured_profile_explains():
    cls = registry.get("Barrett 2050")
    r = cls(NullTransport())
    with pytest.raises(ConfigError, match="not set up yet"):
        r.set_frequency(7e6)


def test_profile_driver_uses_templates():
    prof = {"model": "Test HF", "vendor": "Test", "terminator": "\\r",
            "modes": {"USB": "U"}, "bands_mhz": [[1, 30]],
            "commands": {"set_frequency": "F{hz}", "get_frequency": "F?",
                         "frequency_reply": r"F(\d+)", "set_mode": "M{mode}",
                         "squelch_open": "S?", "squelch_open_reply": "S1"}}
    cls = make_driver(json.loads(json.dumps(prof)), "test.json")
    t = NullTransport(responder=lambda d: {b"F?\r": b"F7100000\r", b"S?\r": b"S1\r"}
                      .get(bytes(d), b""))
    r = cls(t)
    r.connect()
    r.set_frequency(7_100_000)
    r.set_mode("USB")
    assert t.written.startswith(b"F7100000\rMU\r")
    assert r.get_frequency() == 7_100_000
    assert r.squelch_open()


def test_controller_audio_only_cannot_tune():
    from bosun.control import Controller

    ctl = Controller()
    st = ctl.connect_audio_only("RT-950 Pro")
    assert st["connected"] and ctl.audio_only
    with pytest.raises(BosunError):
        ctl.tune("145.5", "FM")
