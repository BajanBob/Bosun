import wave

import numpy as np
import pytest

from bosun import sstv


def picture():
    img = np.zeros((240, 320, 3), np.uint8)
    for i, c in enumerate([(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
                           (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]):
        img[:120, i * 40:(i + 1) * 40] = c
    img[120:] = np.linspace(0, 255, 320)[None, :, None].astype(np.uint8)
    return img


def decode(audio, chunk=4096):
    got = {}
    dec = sstv.SSTVDecoder(48000, on_start=lambda m: got.setdefault("mode", m.name),
                           on_done=lambda im, m: got.setdefault("img", im.copy()))
    for k in range(0, len(audio), chunk):
        dec.feed(audio[k:k + chunk])
    return got


def resized(img, mode):
    ys = np.linspace(0, img.shape[0] - 1, mode.lines).astype(int)
    xs = np.linspace(0, img.shape[1] - 1, mode.width).astype(int)
    return img[ys][:, xs].astype(float)


@pytest.mark.parametrize("name", ["Martin M2", "Scottie S2", "Robot 36", "PD90"])
def test_round_trip_with_noise(name):
    mode = sstv.BY_NAME[name]
    rng = np.random.default_rng(1)
    audio = np.concatenate([np.zeros(20000, np.float32), sstv.encode(picture(), mode),
                            np.zeros(20000, np.float32)])
    audio += rng.standard_normal(len(audio)).astype(np.float32) * 0.2
    got = decode(audio)
    assert got.get("mode") == name
    err = np.abs(got["img"].astype(float) - resized(picture(), mode)).mean()
    assert err < 25, err


def test_tolerates_sound_card_clock_error():
    # Receiving sound card 0.2 % fast: per-line sync tracking keeps it straight.
    mode = sstv.BY_NAME["Martin M2"]
    audio = sstv.encode(picture(), mode)
    x = np.arange(0, len(audio), 1 / 1.002)
    fast = np.interp(x, np.arange(len(audio)), audio).astype(np.float32)
    got = decode(np.concatenate([np.zeros(20000, np.float32), fast, np.zeros(30000, np.float32)]))
    err = np.abs(got["img"].astype(float) - resized(picture(), mode)).mean()
    assert err < 20, err


def test_silence_and_noise_decode_nothing():
    rng = np.random.default_rng(2)
    assert decode(rng.standard_normal(48000 * 5).astype(np.float32) * 0.3) == {}


def test_read_wav(tmp_path):
    path = tmp_path / "s.wav"
    tone = (np.sin(np.arange(44100) * 2 * np.pi * 1900 / 44100) * 20000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(tone.tobytes())
    data = sstv.read_wav(str(path))
    assert abs(len(data) - 48000) <= 2 and 0.5 < np.abs(data).max() < 0.7
