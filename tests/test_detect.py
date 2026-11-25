import threading

from bosun import detect
from bosun.transport import NullTransport


def fake_radio(kind, right_baud, reply_id=None, addr=None):
    def factory(port, baud):
        def respond(data):
            if baud != right_baud:
                return b"\x00\xff" if data else b""  # garbage at the wrong speed
            if kind == "cat" and data == b"ID;":
                return f"ID{reply_id};".encode()
            if kind == "civ" and data == bytes([0xFE, 0xFE, addr, 0x03, 0xFD]):
                return bytes([0xFE, 0xFE, 0xE0, addr, 0x03, 0, 0, 0x50, 0x45, 1, 0xFD])
            return b""
        return NullTransport(responder=respond)
    return factory


def test_identifies_yaesu():
    hit = detect.identify("COM5", factory=fake_radio("cat", 38400, "0670"), timeout=0.05)
    assert (hit.model, hit.baud) == ("FT-991A", 38400)


def test_identifies_ft710_and_kenwood_at_other_speeds():
    hit = detect.identify("COM6", factory=fake_radio("cat", 115200, "0800"), timeout=0.05)
    assert (hit.model, hit.baud) == ("FT-710", 115200)
    hit = detect.identify("COM7", factory=fake_radio("cat", 9600, "020"), timeout=0.05)
    assert (hit.model, hit.baud) == ("TS-480", 9600)


def test_unlisted_ids_fall_back_to_common_command_set():
    hit = detect.identify("COM8", factory=fake_radio("cat", 38400, "0999"), timeout=0.05)
    assert hit.model == "FT-991A" and "unlisted" in hit.detail
    hit = detect.identify("COM8", factory=fake_radio("cat", 38400, "099"), timeout=0.05)
    assert hit.model == "TS-590SG" and "unlisted" in hit.detail


def test_identifies_icom_by_civ_address():
    hit = detect.identify("/dev/ttyUSB0", hint="Icom",
                          factory=fake_radio("civ", 19200, addr=0xA2), timeout=0.05)
    assert (hit.model, hit.baud) == ("IC-9700", 19200)
    hit = detect.identify("/dev/ttyUSB0", factory=fake_radio("civ", 115200, addr=0x94),
                          timeout=0.05)
    assert hit.model == "IC-7300"


def test_silent_device_is_not_a_radio():
    assert detect.identify("COM9", factory=lambda p, b: NullTransport(), timeout=0.02) is None


def test_port_hints():
    info = detect.PortInfo("COM3", 0x10C4, 0xEA60, "IC-9100 USB serial")
    assert info.maker_hint() == "Icom" and "CP210x" in info.label()
    assert detect.PortInfo("COM4", 0x1A86, 0x7523).is_programming_cable
    assert detect.PortInfo("x", description="FTDX10 Enhanced COM Port").maker_hint() == "Yaesu"


def test_watcher_reports_changes(monkeypatch):
    ports = [{"COM1": detect.PortInfo("COM1")}]
    sdrs = [[]]
    monkeypatch.setattr(detect, "port_info", lambda: dict(ports[0]))
    monkeypatch.setattr(detect, "sdr_devices", lambda: list(sdrs[0]))
    added, removed, sdr_added = [], [], []
    done = threading.Event()
    w = detect.DeviceWatcher(on_port_added=lambda i: added.append(i.device),
                             on_port_removed=lambda i: removed.append(i.device),
                             on_sdr_added=lambda n: (sdr_added.append(n), done.set()),
                             port_interval=0.02, sdr_interval=0.05)
    w.start()
    ports[0] = {"COM1": detect.PortInfo("COM1"), "COM5": detect.PortInfo("COM5")}
    sdrs[0] = ["rtlsdr:rtl:0"]
    done.wait(2)
    ports[0] = {"COM5": detect.PortInfo("COM5")}
    for _ in range(100):
        if removed:
            break
        threading.Event().wait(0.02)
    w.stop()
    assert added == ["COM5"] and removed == ["COM1"] and sdr_added == ["rtlsdr:rtl:0"]
