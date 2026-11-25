"""Byte transports: serial, TCP, null loopback."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

from .errors import TransportError

DEFAULT_TIMEOUT = 1.0


class Transport(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, size: int, timeout: float = DEFAULT_TIMEOUT) -> bytes: ...

    @abstractmethod
    def flush_input(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class SerialTransport(Transport):
    """USB-serial bridge via pyserial."""

    def __init__(self, port: str, baud: int = 9600, *, settle: float = 0.15) -> None:
        self.port, self.baud, self.settle = port, baud, settle
        self._ser = None
        self._lock = threading.Lock()

    def open(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise TransportError("pyserial not installed") from exc
        try:
            self._ser = serial.Serial(
                self.port, self.baud, timeout=0.05, write_timeout=1.0
            )
        except Exception as exc:
            raise TransportError(f"cannot open {self.port}: {exc}") from exc
        time.sleep(self.settle)

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def write(self, data: bytes) -> None:
        if self._ser is None:
            raise TransportError("port not open")
        with self._lock:
            try:
                self._ser.write(data)
                self._ser.flush()
            except Exception as exc:
                raise TransportError(f"write failed: {exc}") from exc

    def read(self, size: int, timeout: float = DEFAULT_TIMEOUT) -> bytes:
        if self._ser is None:
            raise TransportError("port not open")
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while len(buf) < size and time.monotonic() < deadline:
            try:
                chunk = self._ser.read(size - len(buf))
            except Exception as exc:
                raise TransportError(f"read failed: {exc}") from exc
            if chunk:
                buf += chunk
            else:
                time.sleep(0.002)
        return bytes(buf)

    def flush_input(self) -> None:
        if self._ser is not None:
            self._ser.reset_input_buffer()

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open


class TCPTransport(Transport):
    """ser2net and LAN-to-serial adapters. Unauthenticated."""

    def __init__(self, host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self._sock = None

    def open(self) -> None:
        import socket

        try:
            self._sock = socket.create_connection((self.host, self.port), self.timeout)
            self._sock.settimeout(self.timeout)
        except OSError as exc:
            raise TransportError(f"cannot reach {self.host}:{self.port}: {exc}") from exc

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise TransportError("socket not open")
        self._sock.sendall(data)

    def read(self, size: int, timeout: float = DEFAULT_TIMEOUT) -> bytes:
        if self._sock is None:
            raise TransportError("socket not open")
        self._sock.settimeout(timeout)
        try:
            return self._sock.recv(size)
        except OSError as exc:
            raise TransportError(f"recv failed: {exc}") from exc

    def flush_input(self) -> None:
        if self._sock is None:
            return
        self._sock.settimeout(0.01)
        try:
            while self._sock.recv(4096):
                pass
        except OSError:
            pass

    @property
    def is_open(self) -> bool:
        return self._sock is not None


class NullTransport(Transport):
    """Test loopback: write() feeds read()."""

    def __init__(self, responder=None) -> None:
        self._rx = bytearray()
        self._open = False
        self._responder = responder
        self.written = bytearray()

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, data: bytes) -> None:
        self.written += data
        if self._responder is not None:
            reply = self._responder(bytes(data))
            if reply:
                self._rx += reply

    def read(self, size: int, timeout: float = DEFAULT_TIMEOUT) -> bytes:
        chunk = bytes(self._rx[:size])
        del self._rx[: len(chunk)]
        return chunk

    def flush_input(self) -> None:
        self._rx.clear()

    @property
    def is_open(self) -> bool:
        return self._open


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]
