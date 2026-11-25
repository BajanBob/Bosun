import pytest

from bosun.control import (
    Controller,
    describe_catalogue,
    format_status,
    models,
    modes_for,
    parse_endpoint,
    parse_mhz,
)
from bosun.errors import BosunError
from bosun.transport import NullTransport


def test_models_and_modes():
    assert "IC-9700" in models()
    assert "USB" in modes_for("FT-991A")
    assert "AR-8600" in describe_catalogue()


def test_parse_endpoint():
    assert parse_endpoint(" 10.0.0.5 ", "4000") == ("10.0.0.5", 4000)
    for host, port in (("", "1"), ("h", "x"), ("h", "70000")):
        with pytest.raises(BosunError):
            parse_endpoint(host, port)


def test_parse_mhz_accepts_comma_decimal():
    assert parse_mhz("145,5") == 145_500_000
    with pytest.raises(BosunError):
        parse_mhz("-1")


def test_connect_tune_and_disconnect():
    made = []

    def factory(host, port):
        t = NullTransport(responder=lambda d: b"")
        made.append((host, port, t))
        return t

    ctl = Controller(transport_factory=factory)
    with pytest.raises(BosunError):
        ctl.status()
    st = ctl.connect("IC-9700", "radio.local", "4000")
    assert st["connected"] is True and made[0][:2] == ("radio.local", 4000)
    ctl.tune("145.5", "FM")
    assert made[0][2].written.startswith(b"\xfe\xfe")
    assert "IC-9700" in format_status(st)
    ctl.disconnect()
    assert not ctl.connected


def test_scan_starts_and_stops():
    ctl = Controller(transport_factory=lambda h, p: NullTransport(responder=lambda d: b""))
    ctl.connect("AR-8600", "h", "1")
    steps = []
    ctl.start_scan("145.0", "145.1", "25", "0.01", on_step=steps.append)
    import time
    time.sleep(0.2)
    ctl.stop_scan()
    assert steps and ctl.scan is None
