"""Live listening: the receive -> DSP -> demodulator -> speaker chain.

SDRListener is an IQ tap (the spectrum feeds it an unbroken stream): it
demodulates the selected signal, applies squelch, de-emphasis and volume, and
plays it. RadioMonitor passes a sound input (e.g. the radio's USB audio)
straight to the speakers.
"""

from __future__ import annotations

import threading

import numpy as np

from .errors import CodecError
from .recorder import AUDIO_RATE, Demodulator


class AudioOut:
    """Speaker output with a small jitter buffer (sounddevice)."""

    def __init__(self, device=None, rate: int = AUDIO_RATE, latency_s: float = 0.25) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:
            raise CodecError(f"audio output unavailable: {exc}") from exc
        self.rate = rate
        self.max_buffer = int(rate * 0.6)
        self.prefill = int(rate * latency_s * 0.5)
        self._buf = np.zeros(0, np.float32)
        self._lock = threading.Lock()
        self._started = False
        self.level = 0.0

        def callback(outdata, frames, _time, _status):
            with self._lock:
                if not self._started and len(self._buf) >= self.prefill:
                    self._started = True
                if self._started and len(self._buf) >= frames:
                    out, self._buf = self._buf[:frames], self._buf[frames:]
                else:
                    have = len(self._buf) if self._started else 0
                    out = np.concatenate([self._buf[:have], np.zeros(frames - have,
                                                                     np.float32)])
                    self._buf = self._buf[have:]
                    if self._started and have < frames:
                        self._started = False  # underrun: refill before restarting
            outdata[:, 0] = out
            self.level = float(np.sqrt(np.mean(out ** 2))) if len(out) else 0.0

        try:
            self._stream = sd.OutputStream(device=device, channels=1, samplerate=rate,
                                           dtype="float32", latency=latency_s,
                                           callback=callback)
            self._stream.start()
        except Exception as exc:
            raise CodecError(f"cannot open the speakers: {exc}") from exc

    def push(self, audio: np.ndarray) -> None:
        with self._lock:
            self._buf = np.concatenate([self._buf, np.asarray(audio, np.float32)])
            if len(self._buf) > self.max_buffer:  # running behind: drop the oldest
                self._buf = self._buf[-self.prefill * 2:]

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


def _iir1(x: np.ndarray, a: float, y0: float) -> tuple[np.ndarray, float]:
    """y[n] = a*y[n-1] + (1-a)*x[n], vectorised in blocks (exact)."""
    n = len(x)
    if n == 0:
        return x, y0
    out = np.empty(n, np.float64)
    block = 256  # keep powers of `a` well conditioned
    p = a ** np.arange(1, block + 1)
    for s in range(0, n, block):
        seg = x[s:s + block].astype(np.float64) * (1 - a)
        m = len(seg)
        # y[k] = a^(k+1) y0 + sum_{j<=k} a^(k-j) seg[j]
        w = a ** -np.arange(m)
        acc = np.cumsum(seg * w) * (a ** np.arange(m))
        out[s:s + m] = acc + p[:m] * y0
        y0 = out[s + m - 1]
    return out.astype(np.float32), float(y0)


class SDRListener:
    """IQ tap that plays the selected signal through the speakers."""

    TAU = {"WFM": 50e-6, "FM": 750e-6, "NFM": 750e-6}  # 50 us broadcast (75 us Americas)

    def __init__(self, out: AudioOut, rate: float, center_hz: float, signal_hz: float,
                 mode: str = "FM", volume: float = 0.7, squelch_db: float = 0.0) -> None:
        self.out = out
        self.rate, self.center_hz = rate, center_hz
        self.mode = mode.upper()
        self.volume, self.squelch_db = volume, squelch_db
        self.signal_hz = signal_hz
        self._demod = Demodulator(rate, signal_hz - center_hz, self.mode)
        self._noise: float | None = None
        self._y = 0.0
        self._gain = 1.0
        self.open = False
        self.snr_db = 0.0
        self.tau = self.TAU.get(self.mode, 0.0)

    def retarget(self, center_hz: float, signal_hz: float, mode: str | None = None,
                 rate: float | None = None) -> None:
        self.center_hz, self.signal_hz = center_hz, signal_hz
        if mode:
            self.mode = mode.upper()
            self.tau = self.TAU.get(self.mode, 0.0)
        self.rate = rate or self.rate
        self._demod = Demodulator(self.rate, signal_hz - center_hz, self.mode)
        self._noise = None

    def _channel_power(self, iq: np.ndarray) -> float:
        return float(np.mean(np.abs(iq) ** 2)) + 1e-20

    def write(self, iq: np.ndarray) -> None:
        audio = self._demod.process(iq)
        if not len(audio):
            return
        # Squelch on the demodulator's channel power relative to the quietest
        # level seen recently (a running noise estimate).
        p = float(getattr(self._demod, "last_power", 0.0)) or self._channel_power(iq)
        self._noise = p if self._noise is None else min(p, self._noise * 1.002)
        self.snr_db = 10 * np.log10(p / self._noise)
        self.open = self.snr_db >= self.squelch_db
        if self.tau:
            audio, self._y = _iir1(audio, float(np.exp(-1 / (AUDIO_RATE * self.tau))),
                                   self._y)
        # automatic level: aim for a comfortable loudness, then the volume knob
        peak = float(np.percentile(np.abs(audio), 99)) + 1e-9
        self._gain += 0.2 * (0.5 / peak - self._gain)
        audio = np.clip(audio * self._gain * self.volume, -1, 1)
        if not self.open:
            audio = np.zeros_like(audio)
        self.out.push(audio)


class RadioMonitor:
    """Plays a sound input (the radio's audio) through the speakers."""

    def __init__(self, in_device=None, out: AudioOut | None = None, volume: float = 1.0):
        try:
            import sounddevice as sd
        except Exception as exc:
            raise CodecError(f"audio unavailable: {exc}") from exc
        self.out = out or AudioOut()
        self.volume = volume
        self.level = 0.0

        def cb(indata, _frames, _t, _status):
            x = indata[:, 0] * self.volume
            self.level = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
            self.out.push(x)

        if isinstance(in_device, str) and ":" in in_device:
            in_device = int(in_device.split(":", 1)[0])
        try:
            self._stream = sd.InputStream(device=in_device, channels=1,
                                          samplerate=AUDIO_RATE, dtype="float32",
                                          blocksize=1024, callback=cb)
            self._stream.start()
        except Exception as exc:
            self.out.close()
            raise CodecError(f"cannot open the audio input: {exc}") from exc

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self.out.close()
