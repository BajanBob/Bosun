import numpy as np

from bosun.listen import SDRListener


class FakeOut:
    def __init__(self):
        self.audio = []

    def push(self, a):
        self.audio.append(np.asarray(a))


def fm_tone(rate, offset, tone, n, dev=3000, noise=0.01, seed=0):
    t = np.arange(n) / rate
    ph = 2 * np.pi * offset * t + dev / tone * np.sin(2 * np.pi * tone * t)
    rng = np.random.default_rng(seed)
    return (np.exp(1j * ph) + noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
            ).astype(np.complex64)


def dominant_hz(audio, rate=48000):
    spec = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    return np.fft.rfftfreq(len(audio), 1 / rate)[np.argmax(spec[10:]) + 10]


def test_fm_signal_is_heard_as_its_tone():
    rate, out = 1.024e6, FakeOut()
    lst = SDRListener(out, rate, 145.0e6, 145.2e6, "FM")
    iq = fm_tone(rate, 200e3, 1000, int(rate))
    for k in range(0, len(iq), 102400):
        lst.write(iq[k:k + 102400])
    audio = np.concatenate(out.audio)
    assert abs(len(audio) - 48000) < 500  # one second in, one second out
    assert abs(dominant_hz(audio[4800:]) - 1000) < 20


def test_am_and_retarget():
    rate, out = 1.024e6, FakeOut()
    t = np.arange(int(rate)) / rate
    iq = ((1 + 0.5 * np.sin(2 * np.pi * 700 * t)) * np.exp(2j * np.pi * -100e3 * t)
          ).astype(np.complex64)
    lst = SDRListener(out, rate, 120e6, 145e6, "FM")
    lst.retarget(120e6, 119.9e6, "AM")
    for k in range(0, len(iq), 102400):
        lst.write(iq[k:k + 102400])
    assert abs(dominant_hz(np.concatenate(out.audio)[4800:]) - 700) < 20


def test_squelch_mutes_noise_then_opens_for_signal():
    rate, out = 1.024e6, FakeOut()
    lst = SDRListener(out, rate, 145e6, 145.1e6, "FM", squelch_db=10)
    rng = np.random.default_rng(1)
    for _ in range(5):
        lst.write((0.01 * (rng.standard_normal(102400) + 1j * rng.standard_normal(102400))
                   ).astype(np.complex64))
    assert not lst.open and np.abs(np.concatenate(out.audio)).max() == 0
    lst.write(fm_tone(rate, 100e3, 1000, 102400))
    assert lst.open and np.abs(out.audio[-1]).max() > 0
