"""Recording: SDR IQ (SigMF), demodulated audio (WAV) and sound-card audio (WAV)."""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import threading
import wave

import numpy as np

from .errors import CodecError
from .version import __version__

AUDIO_RATE = 48_000


def recordings_dir() -> pathlib.Path:
    path = pathlib.Path.home() / "Bosun Recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stamp(prefix: str, hz: float | None = None) -> str:
    t = _dt.datetime.now(_dt.UTC).strftime("%Y%m%d_%H%M%SZ")
    return f"{prefix}_{hz / 1e6:.4f}MHz_{t}" if hz else f"{prefix}_{t}"


# ------------------------------------------------------------------ IQ
class IQRecorder:
    """Writes complex64 IQ plus a SigMF metadata file other tools can open."""

    def __init__(self, center_hz: float, rate: float, folder: pathlib.Path | None = None,
                 description: str = "") -> None:
        base = (folder or recordings_dir()) / stamp("iq", center_hz)
        self.data_path = base.parent / (base.name + ".sigmf-data")
        self.meta_path = base.parent / (base.name + ".sigmf-meta")
        self.center_hz, self.rate = center_hz, rate
        self.samples = 0
        self._fh = open(self.data_path, "wb")  # noqa: SIM115 - kept open while recording
        self._meta = {
            "global": {
                "core:datatype": "cf32_le", "core:sample_rate": rate,
                "core:version": "1.0.0", "core:recorder": f"Bosun {__version__}",
                "core:description": description,
            },
            "captures": [{
                "core:sample_start": 0, "core:frequency": center_hz,
                "core:datetime": _dt.datetime.now(_dt.UTC).isoformat(),
            }],
            "annotations": [],
        }

    def write(self, iq: np.ndarray) -> None:
        if self._fh is None:
            return
        data = np.asarray(iq, dtype=np.complex64)
        data.tofile(self._fh)
        self.samples += len(data)

    def annotate(self, start: int, count: int, label: str, lo_hz: float, hi_hz: float):
        self._meta["annotations"].append({
            "core:sample_start": start, "core:sample_count": count,
            "core:label": label, "core:freq_lower_edge": lo_hz,
            "core:freq_upper_edge": hi_hz,
        })

    def close(self) -> pathlib.Path:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
            self.meta_path.write_text(json.dumps(self._meta, indent=2), encoding="utf-8")
        return self.data_path


# ------------------------------------------------------------------ demod
def _lowpass(cutoff: float, rate: float, taps: int = 129) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff / rate * n) * np.hamming(taps)
    return (h / h.sum()).astype(np.float32)


class Demodulator:
    """Shift a signal to baseband, filter, demodulate and resample to 48 kHz."""

    def __init__(self, rate: float, offset_hz: float, mode: str = "FM",
                 bandwidth_hz: float | None = None) -> None:
        self.rate, self.offset, self.mode = rate, offset_hz, mode.upper()
        bw = bandwidth_hz or {"WFM": 200e3, "FM": 12.5e3, "NFM": 12.5e3, "AM": 8e3,
                              "USB": 3e3, "LSB": 3e3, "CW": 800}.get(self.mode, 12.5e3)
        self.decim = max(1, int(rate // max(bw * 2, AUDIO_RATE)))
        self.mid_rate = rate / self.decim
        self.taps = _lowpass(bw / 2, rate)
        self._n = 0
        self._prev = np.complex64(1)
        self._zi = np.zeros(len(self.taps) - 1, np.complex64)

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = np.asarray(iq, dtype=np.complex64)
        n = np.arange(self._n, self._n + len(iq))
        self._n += len(iq)
        shifted = iq * np.exp(-2j * np.pi * self.offset * n / self.rate).astype(np.complex64)
        buf = np.concatenate([self._zi, shifted])
        filt = np.convolve(buf, self.taps, mode="valid")
        self._zi = buf[-(len(self.taps) - 1):]
        base = filt[:: self.decim]
        if self.mode in ("FM", "NFM", "WFM"):
            prev = np.concatenate([[self._prev], base[:-1]])
            audio = np.angle(base * np.conj(prev)).astype(np.float32)
            if len(base):
                self._prev = base[-1]
        elif self.mode == "AM":
            env = np.abs(base)
            audio = (env - np.mean(env)).astype(np.float32)
        else:  # USB/LSB/CW: product detector at baseband
            audio = (base.real if self.mode != "LSB" else -base.imag).astype(np.float32)
        # Resample to 48 kHz by linear interpolation.
        if not len(audio):
            return audio
        count = int(len(audio) * AUDIO_RATE / self.mid_rate)
        x = np.linspace(0, len(audio) - 1, max(count, 1))
        return np.interp(x, np.arange(len(audio)), audio).astype(np.float32)


class WavWriter:
    def __init__(self, path: pathlib.Path, rate: int = AUDIO_RATE, channels: int = 1):
        self.path = path
        self._w = wave.open(str(path), "wb")  # noqa: SIM115 - kept open while recording
        self._w.setnchannels(channels)
        self._w.setsampwidth(2)
        self._w.setframerate(rate)
        self._peak = 1e-3
        self.frames = 0

    def write(self, audio: np.ndarray) -> None:
        if self._w is None or not len(audio):
            return
        audio = np.asarray(audio, dtype=np.float32)
        if audio.dtype.kind == "f":
            self._peak = max(self._peak * 0.999, float(np.max(np.abs(audio))))
            audio = np.clip(audio / self._peak * 0.8, -1, 1)
        self._w.writeframes((audio * 32767).astype("<i2").tobytes())
        self.frames += len(audio)

    def close(self) -> pathlib.Path:
        if self._w is not None:
            self._w.close()
            self._w = None
        return self.path


class SDRAudioRecorder:
    """Demodulates one signal from the SDR stream to a WAV file."""

    def __init__(self, source_rate: float, center_hz: float, signal_hz: float,
                 mode: str, folder: pathlib.Path | None = None) -> None:
        self.demod = Demodulator(source_rate, signal_hz - center_hz, mode)
        path = (folder or recordings_dir()) / (stamp(f"audio_{mode.lower()}", signal_hz) + ".wav")
        self.wav = WavWriter(path)

    def write(self, iq: np.ndarray) -> None:
        self.wav.write(self.demod.process(iq))

    def close(self) -> pathlib.Path:
        return self.wav.close()


# ------------------------------------------------------------------ sound card
def input_devices() -> list[str]:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise CodecError(f"audio input unavailable: {exc}") from exc
    return [f"{i}: {d['name']}" for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0]


class SoundCardRecorder:
    """Records a sound-card input (radio audio via USB codec or line-in)."""

    def __init__(self, device: str | int | None = None, rate: int = AUDIO_RATE,
                 folder: pathlib.Path | None = None, label: str = "radio") -> None:
        try:
            import sounddevice as sd
        except Exception as exc:
            raise CodecError(f"audio input unavailable: {exc}") from exc
        if isinstance(device, str) and ":" in device:
            device = int(device.split(":", 1)[0])
        path = (folder or recordings_dir()) / (stamp(f"audio_{label}") + ".wav")
        self.wav = WavWriter(path, rate)
        self.level = 0.0
        self._lock = threading.Lock()

        def callback(indata, frames, _time, _status):
            mono = indata[:, 0].astype(np.float32)
            self.level = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
            with self._lock:
                self.wav._w.writeframes((np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes())
                self.wav.frames += frames

        try:
            self._stream = sd.InputStream(device=device, channels=1, samplerate=rate,
                                          dtype="float32", callback=callback)
            self._stream.start()
        except Exception as exc:
            self.wav.close()
            raise CodecError(f"cannot open audio input: {exc}") from exc

    @property
    def seconds(self) -> float:
        return self.wav.frames / AUDIO_RATE

    def close(self) -> pathlib.Path:
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            with self._lock:
                path = self.wav.close()
        return path
