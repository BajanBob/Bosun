import socket
import struct
import threading
import time
import zlib

import numpy as np
import pytest

from bosun import dsp
from bosun.errors import SDRUnavailable
from bosun.raster import Waterfall, png_bytes
from bosun.sources import DemoSource, RtlTcpSource, open_source, parse_rtl_tcp


class FakeRtlTcp:
    """Minimal rtl_tcp server streaming the demo band as uint8 IQ."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.commands = []
        self.demo = DemoSource(145.2e6, 1.024e6, seed=7)
        self.stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.srv.accept()
        conn.sendall(b"RTL0" + struct.pack(">II", 5, 29))
        conn.settimeout(0.01)
        while not self.stop:
            try:
                data = conn.recv(5)
                if len(data) == 5:
                    cmd, val = struct.unpack(">BI", data)
                    self.commands.append((cmd, val))
                    if cmd == 1:
                        self.demo.center_hz = val
            except (TimeoutError, BlockingIOError):
                pass
            except OSError:
                break
            iq = self.demo.read(16384) * 6
            raw = np.empty(len(iq) * 2, np.float32)
            raw[0::2], raw[1::2] = iq.real, iq.imag
            try:
                conn.sendall((raw * 127 + 127.4).clip(0, 255).astype(np.uint8).tobytes())
            except OSError:
                break
            time.sleep(0.005)
        conn.close()


@pytest.fixture
def server():
    s = FakeRtlTcp()
    yield s
    s.stop = True


def test_parse_spec():
    assert parse_rtl_tcp("rtl_tcp:10.0.0.2:1234") == ("10.0.0.2", 1234)
    assert parse_rtl_tcp("rtl_tcp:127.0.0.1:7000") == ("127.0.0.1", 7000)


def test_streams_and_detects(server):
    src = open_source(f"rtl_tcp:127.0.0.1:{server.port}", 145.6e6, 1.024e6, 20)
    try:
        time.sleep(0.3)
        assert (2, 1_024_000) in server.commands and (1, 145_600_000) in server.commands
        assert (4, 200) in server.commands  # 20 dB in tenths
        iq = src.read(16384)
        off, p = dsp.psd(iq, src.rate)
        found = dsp.detect(off, p, src.center_hz)
        assert any(abs(d.center_hz - 145.8e6) < 5e3 for d in found)
        src.tune(146.0e6)
        time.sleep(0.1)
        assert (1, 146_000_000) in server.commands
        src.set_gain(None)
        time.sleep(0.05)
        assert (3, 0) in server.commands
    finally:
        src.close()


def test_not_a_server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]

    def answer():
        c, _ = s.accept()
        c.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
        c.close()

    threading.Thread(target=answer, daemon=True).start()
    with pytest.raises(SDRUnavailable, match="not an rtl_tcp"):
        RtlTcpSource("127.0.0.1", port, connect_timeout=1).open()
    s.close()


def test_nothing_listening():
    with pytest.raises(SDRUnavailable, match="cannot reach"):
        RtlTcpSource("127.0.0.1", 1, connect_timeout=0.5).open()


def test_png_raster():
    w = Waterfall(200, 50, 60)
    src = DemoSource(145.2e6, seed=1)
    off, p = dsp.psd(src.read(16384), src.rate)
    w.push(off + src.center_hz, p)
    data = w.png(dsp.detect(off, p, src.center_hz), 145.5e6)
    assert data.startswith(b"\x89PNG") and b"IDAT" in data
    idat = data.index(b"IDAT")
    size = struct.unpack(">I", data[idat - 4: idat])[0]
    raw = zlib.decompress(data[idat + 4: idat + 4 + size])
    assert len(raw) == 110 * (1 + 200 * 3)
    assert png_bytes(np.zeros((2, 3, 3), np.uint8))[:8] == b"\x89PNG\r\n\x1a\n"
