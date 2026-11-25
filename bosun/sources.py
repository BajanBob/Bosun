"""IQ sources for the spectrum view: real SDRs and a built-in simulator."""

from __future__ import annotations

import contextlib
import threading
import time

import numpy as np

from .errors import SDRUnavailable

DEFAULT_RATE = 2.048e6


class IQSource:
    name = "abstract"
    rate = DEFAULT_RATE
    max_rate = 2.4e6  # widest span the device streams reliably; wider = sweep
    center_hz = 100e6
    min_hz, max_hz = 0.0, 6e9

    def open(self) -> None: ...
    def close(self) -> None: ...
    def tune(self, hz: float) -> None:
        self.center_hz = float(hz)

    def set_gain(self, db: float) -> None: ...
    def read(self, n: int) -> np.ndarray:
        raise NotImplementedError


class DemoSource(IQSource):
    """Simulated band: steady carriers, a voice-like FM channel that keys up and
    down, a broadcast station and noise. For trying Bosun without hardware."""

    name = "Demo (simulated signals)"

    def __init__(self, center_hz: float = 145.0e6, rate: float = DEFAULT_RATE,
                 seed: int | None = None) -> None:
        self.center_hz, self.rate = center_hz, rate
        self._rng = np.random.default_rng(seed)
        self._t0 = time.monotonic()
        self._phase = 0.0

    def _emitters(self, now: float):
        # (absolute Hz, amplitude, kind, on?)
        return [
            (145.500e6, 0.05, "fm", (now % 6) < 3.5),          # repeater keying
            (145.800e6, 0.02, "cw", True),                      # beacon
            (144.390e6, 0.015, "fm", (now % 10) < 1.2),          # packet burst
            (146.520e6, 0.03, "fm", (now % 9) > 5),
            (100.1e6, 0.2, "wfm", True),                        # FM broadcast
            (121.500e6, 0.04, "am", (now % 7) < 4),             # airband
            (14.074e6, 0.01, "narrow", True),                   # FT8-ish
            (145.900e6, 0.03, "sstv", True),                    # SSTV picture loop
            (7.100e6, 0.03, "ssb", (now % 5) < 3),
        ]

    _sstv_audio: np.ndarray | None = None

    @classmethod
    def sstv_audio(cls) -> np.ndarray:
        """A Robot 36 test picture followed by 8 s of silence, made once."""
        if cls._sstv_audio is None:
            from .sstv import BY_NAME, encode

            img = np.zeros((240, 320, 3), np.uint8)
            cols = [(255, 255, 255), (212, 175, 55), (46, 204, 113), (15, 81, 50),
                    (200, 40, 40), (40, 90, 200), (120, 120, 120), (0, 0, 0)]
            for i, c in enumerate(cols):
                img[:150, i * 40:(i + 1) * 40] = c
            img[150:] = np.linspace(0, 255, 320)[None, :, None].astype(np.uint8)
            cls._sstv_audio = np.concatenate([encode(img, BY_NAME["Robot 36"]),
                                              np.zeros(48000 * 8, np.float32)])
        return cls._sstv_audio

    def _voice(self, n: int, bw_hz: float) -> np.ndarray:
        """Band-limited random 'audio', -1..1."""
        taps = max(2, int(self.rate / bw_hz))
        x = np.convolve(self._rng.standard_normal(n + taps), np.ones(taps) / taps, "valid")[:n]
        return (x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)

    def read(self, n: int) -> np.ndarray:
        t = (np.arange(n) + self._phase) / self.rate
        self._phase += n
        noise = (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n)) * 0.002
        out = noise.astype(np.complex64)
        now = time.monotonic() - self._t0
        half = self.rate / 2
        for hz, amp, kind, on in self._emitters(now):
            off = hz - self.center_hz
            if not on or abs(off) > half * 0.98:
                continue
            carrier = 2 * np.pi * off * t
            if kind == "cw":
                sig = np.exp(1j * carrier)
            elif kind in ("fm", "wfm"):
                dev = 2_500 if kind == "fm" else 60_000
                audio = self._voice(n, 3_000 if kind == "fm" else 15_000)
                phase = 2 * np.pi * dev * np.cumsum(audio) / self.rate
                sig = np.exp(1j * (carrier + phase))
            elif kind == "sstv":
                audio = self.sstv_audio()
                pos = (t * 48000) % len(audio)
                tone = np.interp(pos, np.arange(len(audio)), audio)
                # FM, 3 kHz deviation; phase kept continuous between reads
                inc = 2 * np.pi * (off + 3000 * tone) / self.rate
                ph = getattr(self, "_sstv_phase", 0.0) + np.cumsum(inc)
                self._sstv_phase = float(ph[-1] % (2 * np.pi))
                sig = np.exp(1j * ph)
            elif kind == "am":
                sig = (1 + 0.5 * self._voice(n, 3_000)) * np.exp(1j * carrier)
            elif kind == "ssb":
                tones = sum(np.exp(2j * np.pi * f * t) * a for f, a in
                            ((400, 1), (900, .8), (1700, .6), (2400, .4)))
                sig = tones * np.exp(1j * carrier) / 2.8
            else:
                sig = np.exp(1j * (carrier + 2 * np.pi * 25 * np.sin(2 * np.pi * 3 * t) / 3))
            out += (amp * sig).astype(np.complex64)
        return out


class SDRSource(IQSource):
    """Any Bosun SDR backend (RTL-SDR, SoapySDR devices, Airspy)."""

    def __init__(self, spec: str, center_hz: float = 100e6, rate: float = DEFAULT_RATE,
                 gain_db: float = 30.0) -> None:
        self.spec, self.center_hz, self.rate, self.gain = spec, center_hz, rate, gain_db
        self.name = spec
        self._dev = None
        self._lock = threading.Lock()

    def open(self) -> None:
        from .sdr import open_backend

        try:
            self._dev = open_backend(self.spec)
            self._dev.set_sample_rate(self.rate)
            self._dev.set_frequency(self.center_hz)
            self._dev.set_gain(self.gain)
            caps = self._dev.caps
            if caps.max_hz:
                self.min_hz, self.max_hz = caps.min_hz, caps.max_hz
            # RTL-SDR advertises 3.2 MS/s but drops samples above ~2.4.
            if caps.max_rate:
                self.max_rate = min(caps.max_rate,
                                    2.4e6 if self.spec.startswith("rtl") else caps.max_rate)
        except SDRUnavailable:
            raise
        except Exception as exc:
            raise SDRUnavailable(f"cannot open {self.spec}: {exc}") from exc

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def tune(self, hz: float) -> None:
        self.center_hz = float(hz)
        if self._dev is not None:
            with self._lock:
                self._dev.set_frequency(self.center_hz)

    def set_gain(self, db: float) -> None:
        self.gain = db
        if self._dev is not None:
            with self._lock:
                self._dev.set_gain(db)

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._dev is not None:
            with self._lock:
                self._dev.set_sample_rate(self.rate)

    def read(self, n: int) -> np.ndarray:
        if self._dev is None:
            raise SDRUnavailable("SDR not open")
        with self._lock:
            blocks, got = [], 0
            for block in self._dev.stream(n):
                blocks.append(block)
                got += len(block)
                if got >= n:
                    break
        return np.concatenate(blocks)[:n] if blocks else np.zeros(n, np.complex64)


RTL_TCP_DEFAULT = "rtl_tcp:127.0.0.1:1234"


class RtlTcpSource(IQSource):
    """RTL-SDR over the rtl_tcp protocol.

    Works with rtl_tcp on a PC or Raspberry Pi, and on Android with the
    "Rtl-sdr driver" app (marto.rtl_tcp_andro), which serves a USB dongle on
    127.0.0.1. A reader thread drains the socket so reads are always fresh.
    """

    CMD_FREQ, CMD_RATE, CMD_GAIN_MODE, CMD_GAIN, CMD_AGC = 0x01, 0x02, 0x03, 0x04, 0x08

    def __init__(self, host: str = "127.0.0.1", port: int = 1234, center_hz: float = 100e6,
                 rate: float = 1.024e6, gain_db: float | None = 30.0,
                 connect_timeout: float = 5.0) -> None:
        self.host, self.port = host, int(port)
        self.center_hz, self.rate, self.gain = center_hz, rate, gain_db
        self.timeout = connect_timeout
        self.name = f"rtl_tcp:{host}:{port}"
        self.min_hz, self.max_hz = 24e6, 1766e6
        self.tuner = 0
        self._sock = None
        self._buf = np.zeros(0, np.complex64)
        self._keep = int(rate) * 2  # about two seconds of samples
        self._lock = threading.Lock()
        self._alive = False
        self._thread: threading.Thread | None = None

    def _cmd(self, cmd: int, value: int) -> None:
        import struct

        if self._sock is None:
            raise SDRUnavailable("rtl_tcp not connected")
        self._sock.sendall(struct.pack(">BI", cmd, int(value) & 0xFFFFFFFF))

    def open(self) -> None:
        import socket
        import struct

        try:
            sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as exc:
            raise SDRUnavailable(f"cannot reach rtl_tcp at {self.host}:{self.port}: {exc}"
                                 ) from exc
        sock.settimeout(self.timeout)
        header = b""
        try:
            while len(header) < 12:
                chunk = sock.recv(12 - len(header))
                if not chunk:
                    break
                header += chunk
        except OSError:
            pass
        if len(header) < 12 or not header.startswith(b"RTL"):
            sock.close()
            raise SDRUnavailable(f"{self.host}:{self.port} is not an rtl_tcp server")
        self.tuner = struct.unpack(">I", header[4:8])[0]
        self._sock = sock
        self._cmd(self.CMD_RATE, self.rate)
        self._cmd(self.CMD_FREQ, self.center_hz)
        self.set_gain(self.gain)
        sock.settimeout(1.0)
        self._alive = True
        self._thread = threading.Thread(target=self._reader, daemon=True, name="rtl_tcp")
        self._thread.start()

    def _reader(self) -> None:
        pending = b""
        while self._alive:
            try:
                chunk = self._sock.recv(262144)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
            data = pending + chunk
            usable = len(data) & ~1
            pending = data[usable:]
            raw = np.frombuffer(data[:usable], dtype=np.uint8).astype(np.float32)
            iq = ((raw[0::2] - 127.4) + 1j * (raw[1::2] - 127.4)) / 128.0
            with self._lock:
                self._buf = np.concatenate([self._buf, iq.astype(np.complex64)])[-self._keep:]
        self._alive = False

    def close(self) -> None:
        self._alive = False
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        if self._thread is not None:
            self._thread.join(2)

    def tune(self, hz: float) -> None:
        self.center_hz = float(hz)
        self._cmd(self.CMD_FREQ, self.center_hz)
        with self._lock:
            self._buf = self._buf[:0]  # drop samples from the old frequency

    def set_gain(self, db: float | None) -> None:
        self.gain = db
        if db is None:
            self._cmd(self.CMD_GAIN_MODE, 0)  # automatic
        else:
            self._cmd(self.CMD_GAIN_MODE, 1)
            self._cmd(self.CMD_GAIN, round(float(db) * 10))

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        self._keep = int(rate) * 2
        self._cmd(self.CMD_RATE, self.rate)

    def read_all(self, min_n: int, timeout: float = 3.0) -> np.ndarray:
        """Every sample received since the last read (at least min_n): an
        unbroken stream for audio and decoders."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if len(self._buf) >= min_n:
                    out, self._buf = self._buf, self._buf[:0]
                    return out
            if not self._alive:
                raise SDRUnavailable("rtl_tcp connection closed")
            if time.monotonic() > deadline:
                raise SDRUnavailable("no samples from rtl_tcp (is the dongle plugged in?)")
            time.sleep(0.005)

    def read(self, n: int, timeout: float = 3.0) -> np.ndarray:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if len(self._buf) >= n:
                    out = self._buf[-n:].copy()
                    self._buf = self._buf[:0]
                    return out
            if not self._alive:
                raise SDRUnavailable("rtl_tcp connection closed")
            if time.monotonic() > deadline:
                raise SDRUnavailable("no samples from rtl_tcp (is the dongle plugged in?)")
            time.sleep(0.01)


def find_hackrf_tool(name: str = "hackrf_transfer") -> str | None:
    """hackrf tools from PATH, the folder next to Bosun, or common install places."""
    import os
    import shutil
    import sys

    exe = name + (".exe" if sys.platform.startswith("win") else "")
    found = shutil.which(exe)
    if found:
        return found
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
    places = [here, os.path.join(here, "hackrf")]
    if sys.platform.startswith("win"):
        for root in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")):
            places += [os.path.join(root, "PothosSDR", "bin"),
                       os.path.join(root, "HackRF", "bin"), os.path.join(root, "hackrf")]
    else:
        places += ["/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"]
    for folder in places:
        path = os.path.join(folder, exe)
        if os.path.isfile(path):
            return path
    return None


def hackrf_boards(timeout: float = 4.0) -> list[str]:
    """Serial numbers of attached HackRFs (empty if none or no tools)."""
    import subprocess

    tool = find_hackrf_tool("hackrf_info")
    if not tool:
        return []
    try:
        out = subprocess.run([tool], capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return []
    serials = [ln.split(":", 1)[1].strip() for ln in out.splitlines()
               if ln.strip().lower().startswith("serial number")]
    if not serials and "Found HackRF" in out:
        serials = ["0"]
    return serials


class HackRFSource(IQSource):
    """HackRF One via the standard hackrf_transfer tool (streams int8 IQ).

    Retuning restarts the stream (about half a second). Up to 20 MS/s.
    """

    max_rate = 20e6

    def __init__(self, center_hz: float = 100e6, rate: float = 8e6, gain_db: float = 30.0,
                 serial: str | None = None, amp: bool = False) -> None:
        self.center_hz, self.rate, self.gain = center_hz, rate, gain_db
        self.serial, self.amp = serial, amp
        self.name = "hackrf" + (f":{serial}" if serial and serial != "0" else "")
        self.min_hz, self.max_hz = 1e6, 6e9
        self._proc = None
        self._buf = np.zeros(0, np.complex64)
        self._lock = threading.Lock()
        self._alive = False
        self._thread: threading.Thread | None = None

    def _cmd(self) -> list[str]:
        tool = find_hackrf_tool()
        if not tool:
            raise SDRUnavailable(
                "HackRF tools not found. Install them (hackrf_transfer) from Great Scott "
                "Gadgets, PothosSDR or your package manager, then try again.")
        # LNA 0-40 dB in 8 dB steps, VGA 0-62 dB in 2 dB steps
        lna = int(min(40, max(0, self.gain * 0.6)) // 8 * 8)
        vga = int(min(62, max(0, self.gain - lna + 10)) // 2 * 2)
        cmd = [tool, "-r", "-", "-f", str(int(self.center_hz)), "-s", str(int(self.rate)),
               "-l", str(lna), "-g", str(vga), "-a", "1" if self.amp else "0"]
        if self.serial and self.serial != "0":
            cmd += ["-d", self.serial]
        return cmd

    def open(self) -> None:
        import subprocess

        self.close()
        self._proc = subprocess.Popen(
            self._cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._alive = True
        self._thread = threading.Thread(target=self._reader, daemon=True, name="hackrf")
        self._thread.start()

    def _reader(self) -> None:
        keep = int(self.rate)  # about one second
        pending = b""
        out = self._proc.stdout
        while self._alive:
            chunk = out.read(262144)
            if not chunk:
                break
            data = pending + chunk
            usable = len(data) & ~1
            pending = data[usable:]
            raw = np.frombuffer(data[:usable], dtype=np.int8).astype(np.float32) / 128.0
            iq = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
            with self._lock:
                self._buf = np.concatenate([self._buf, iq])[-keep:]
        self._alive = False

    def close(self) -> None:
        self._alive = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(3)
            except Exception:
                with contextlib.suppress(Exception):
                    self._proc.kill()
            self._proc = None
        with self._lock:
            self._buf = self._buf[:0]

    def tune(self, hz: float) -> None:
        self.center_hz = float(hz)
        if self._proc is not None:
            self.open()

    def set_gain(self, db: float) -> None:
        self.gain = db
        if self._proc is not None:
            self.open()

    def set_rate(self, rate: float) -> None:
        self.rate = float(rate)
        if self._proc is not None:
            self.open()

    def read_all(self, min_n: int, timeout: float = 3.0) -> np.ndarray:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if len(self._buf) >= min_n:
                    out, self._buf = self._buf, self._buf[:0]
                    return out
            if not self._alive:
                raise SDRUnavailable("HackRF stream stopped (is it plugged in and free?)")
            if time.monotonic() > deadline:
                raise SDRUnavailable("no samples from the HackRF")
            time.sleep(0.005)

    def read(self, n: int, timeout: float = 3.0) -> np.ndarray:
        data = self.read_all(n, timeout)
        return data[-n:]


def parse_rtl_tcp(name: str) -> tuple[str, int]:
    rest = name.split(":", 1)[1] if name.startswith("rtl_tcp") else name
    host, _, port = rest.rpartition(":")
    return (host or "127.0.0.1"), int(port or 1234)


def list_sources() -> list[str]:
    """Names for the source picker: the demo plus any SDRs found."""
    names = [DemoSource.name, RTL_TCP_DEFAULT]
    for serial in hackrf_boards():
        names.append("hackrf" + (f":{serial}" if serial != "0" else ""))
    try:
        from .sdr import available

        for key, devs in available().items():
            if key == "file":
                continue
            names += [d if d.startswith(f"{key}:") else f"{key}:{d}" for d in devs]
    except Exception:
        pass
    return names


def open_source(name: str, center_hz: float, rate: float = DEFAULT_RATE,
                gain_db: float = 30.0) -> IQSource:
    if name == DemoSource.name or not name:
        src: IQSource = DemoSource(center_hz, rate)
    elif name.startswith("hackrf"):
        serial = name.split(":", 1)[1] if ":" in name else None
        src = HackRFSource(center_hz, min(max(rate, 2e6), 20e6), gain_db, serial)
    elif name.startswith("rtl_tcp"):
        host, port = parse_rtl_tcp(name)
        src = RtlTcpSource(host, port, center_hz, min(rate, 2.4e6), gain_db)
    else:
        src = SDRSource(name, center_hz, rate, gain_db)
    src.open()
    return src
