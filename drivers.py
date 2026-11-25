"""Backends. Native bindings imported lazily."""

from __future__ import annotations

import numpy as np

from ..errors import SDRUnavailable
from .base import SDRBackend, SDRCaps


def _missing(pkg: str) -> SDRUnavailable:
    return SDRUnavailable(f"{pkg} not installed")


class SoapyBackend(SDRBackend):
    name = "soapy"
    driver_key = "soapy"

    def __init__(self) -> None:
        self._dev = self._stream = None

    @classmethod
    def probe(cls) -> list[str]:
        try:
            import SoapySDR
        except ImportError:
            return []
        return [f"{d['driver']}={d.get('serial', '')}" for d in SoapySDR.Device.enumerate()]

    def open(self, device: str) -> None:
        try:
            import SoapySDR
            from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX
        except ImportError as exc:
            raise _missing("SoapySDR") from exc
        self._dev = SoapySDR.Device(device)
        self._stream = self._dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self._dev.activateStream(self._stream)

    def close(self) -> None:
        if self._dev is not None and self._stream is not None:
            try:
                self._dev.deactivateStream(self._stream)
                self._dev.closeStream(self._stream)
            finally:
                self._dev = self._stream = None

    @property
    def caps(self) -> SDRCaps:
        if self._dev is None:
            return SDRCaps()
        return SDRCaps(
            min_hz=self._dev.getFrequencyRange(0)[0].minimum(),
            max_hz=self._dev.getFrequencyRange(0)[0].maximum(),
            max_rate=self._dev.getSampleRateRange(0)[0].maximum(),
            antennas=list(self._dev.listAntennas(0)),
        )

    def set_frequency(self, hz: float) -> None:
        self._dev.setFrequency(0, hz)

    def set_sample_rate(self, rate: float) -> None:
        self._dev.setSampleRate(0, rate)

    def set_gain(self, db: float, element: str | None = None) -> None:
        self._dev.setGain(0, db, element or "")

    def set_bandwidth(self, hz: float) -> None:
        self._dev.setBandwidth(0, hz)

    def stream(self, nsamples: int):
        import SoapySDR

        buf = np.empty(65536, np.complex64)
        sent = 0
        while sent < nsamples:
            st = self._dev.readStream(self._stream, [buf], len(buf), timeoutUs=1_000_000)
            if st.ret > 0:
                sent += st.ret
                yield buf[: st.ret].copy()
            elif st.ret < 0 and st.ret != SoapySDR.SOAPY_SDR_TIMEOUT:
                raise SDRUnavailable(f"stream error {st.ret}")


class RTLBackend(SDRBackend):
    name = "rtlsdr"
    driver_key = "rtlsdr"

    def __init__(self) -> None:
        self._sdr = None

    @classmethod
    def probe(cls) -> list[str]:
        try:
            from rtlsdr import RtlSdr
        except ImportError:
            return []
        try:
            return [f"rtl:{i}" for i in range(RtlSdr.get_device_count())]
        except Exception:
            return []

    def open(self, device: str) -> None:
        try:
            from rtlsdr import RtlSdr
        except ImportError as exc:
            raise _missing("pyrtlsdr") from exc
        idx = int(device.split(":")[-1]) if ":" in device else 0
        self._sdr = RtlSdr(device_index=idx)

    def close(self) -> None:
        if self._sdr is not None:
            self._sdr.close()
            self._sdr = None

    @property
    def caps(self) -> SDRCaps:
        return SDRCaps(
            min_hz=24e6, max_hz=1766e6, max_rate=3.2e6,
            gain_range=(0.0, 49.6), bias_tee=True,
        )

    def set_frequency(self, hz: float) -> None:
        self._sdr.center_freq = hz

    def set_sample_rate(self, rate: float) -> None:
        self._sdr.sample_rate = rate

    def set_gain(self, db: float, element: str | None = None) -> None:
        self._sdr.gain = db

    def set_bandwidth(self, hz: float) -> None:
        self._sdr.set_bandwidth(hz)

    def stream(self, nsamples: int):
        yield self._sdr.read_samples(nsamples).astype(np.complex64)


class AirspyBackend(SDRBackend):
    name = "airspy"
    driver_key = "airspy"

    def __init__(self) -> None:
        self._sdr = None

    @classmethod
    def probe(cls) -> list[str]:
        try:
            from airspy import Airspy
        except ImportError:
            return []
        return [f"airspy:{s}" for s in Airspy().get_serial_number_list()]

    def open(self, device: str) -> None:
        try:
            from airspy import Airspy
        except ImportError as exc:
            raise _missing("airspy") from exc
        self._sdr = Airspy()
        self._sdr.open(device.split(":")[-1] if ":" in device else "")

    def close(self) -> None:
        if self._sdr is not None:
            self._sdr.close()
            self._sdr = None

    @property
    def caps(self) -> SDRCaps:
        return SDRCaps(
            min_hz=24e6, max_hz=1800e6, max_rate=10e6,
            gain_range=(0.0, 15.0), bias_tee=True,
        )

    def set_frequency(self, hz: float) -> None:
        self._sdr.set_freq(int(hz))

    def set_sample_rate(self, rate: float) -> None:
        self._sdr.set_sample_rate(int(rate))

    def set_gain(self, db: float, element: str | None = None) -> None:
        self._sdr.set_lna_gain(int(max(0, min(15, db))))

    def set_bandwidth(self, hz: float) -> None:
        pass

    def stream(self, nsamples: int):
        self._sdr.start()
        got = 0
        while got < nsamples:
            block = self._sdr.read()
            got += len(block)
            yield block.astype(np.complex64)
        self._sdr.stop()


class FileBackend(SDRBackend):
    name = "file"
    driver_key = "file"

    def __init__(self) -> None:
        self._data = None

    @classmethod
    def probe(cls) -> list[str]:
        return ["file:./capture.cf32"]

    def open(self, device: str) -> None:
        self._data = np.fromfile(device.split(":", 1)[-1], dtype=np.complex64)

    def close(self) -> None:
        self._data = None

    @property
    def caps(self) -> SDRCaps:
        return SDRCaps(min_hz=0.0, max_hz=2e9, max_rate=1e9)

    def set_frequency(self, hz: float) -> None:
        pass

    def set_sample_rate(self, rate: float) -> None:
        pass

    def set_gain(self, db: float, element: str | None = None) -> None:
        pass

    def set_bandwidth(self, hz: float) -> None:
        pass

    def stream(self, nsamples: int):
        if self._data is None:
            raise SDRUnavailable("no file open")
        for i in range(0, min(nsamples, len(self._data)), 65536):
            yield self._data[i : i + 65536]


BACKENDS = {b.driver_key: b for b in
            (SoapyBackend, RTLBackend, AirspyBackend, FileBackend)}
