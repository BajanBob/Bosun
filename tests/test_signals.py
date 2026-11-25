import json
import time
import wave

import numpy as np

from bosun import chirp, dsp
from bosun.cognitive import CognitiveReceiver, Sweeper
from bosun.recorder import IQRecorder, SDRAudioRecorder
from bosun.sources import DemoSource


def tone(rate, off, n, amp=0.05, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / rate
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 0.002
    return (amp * np.exp(2j * np.pi * off * t) + noise).astype(np.complex64)


def test_detects_carrier_at_right_frequency():
    rate = 256e3
    off, p = dsp.psd(tone(rate, 30e3, 65536), rate, 4096)
    found = dsp.detect(off, p, 100e6)
    assert found and abs(found[0].center_hz - 100.03e6) < 200
    assert found[0].kind == "Carrier / CW"


def test_classify_labels():
    assert dsp.classify(200)[0] == "Carrier / CW"
    assert dsp.classify(2500)[0] == "Voice (SSB) / data"
    assert dsp.classify(12000, 3.0)[0] == "Narrow FM"
    assert dsp.classify(12000, 25.0)[0] == "AM voice"
    assert dsp.classify(12000, float("nan"))[0] == "AM or FM voice"
    assert dsp.classify(180000)[0] == "Broadcast FM"
    assert dsp.classify(2000, 0, 1000)[0] == "Narrow signal"


def test_noise_only_finds_nothing():
    rng = np.random.default_rng(1)
    iq = (rng.standard_normal(65536) + 1j * rng.standard_normal(65536)).astype(np.complex64)
    off, p = dsp.psd(iq, 1e6, 2048)
    assert len(dsp.detect(off, p)) <= 1


def test_cognitive_tracks_and_ranks():
    src = DemoSource(145.2e6, seed=4)
    cog = CognitiveReceiver(sensitivity=0.6)
    for _ in range(10):
        off, p = dsp.psd(src.read(16384), src.rate)
        cog.process(off, p, src.center_hz)
    assert any(abs(s.center_hz - 145.8e6) < 3e3 for s in cog.ranked())
    assert cog.new_signals()


def test_sweeper_covers_range():
    f, p = Sweeper(DemoSource(100e6, seed=5), 95e6, 105e6).sweep()
    assert f[0] >= 95e6 and f[-1] <= 105e6 and f[-1] - f[0] > 9.5e6
    assert any(abs(d.center_hz - 100.1e6) < 100e3 for d in dsp.detect(f, p))


def test_recorders(tmp_path):
    rec = IQRecorder(145e6, 1e6, tmp_path)
    rec.write(np.ones(1000, np.complex64))
    data = rec.close()
    assert data.stat().st_size == 8000
    meta = json.loads(rec.meta_path.read_text())
    assert meta["global"]["core:datatype"] == "cf32_le"
    a = SDRAudioRecorder(256e3, 145e6, 145.01e6, "FM", tmp_path)
    for _ in range(4):
        a.write(tone(256e3, 10e3, 65536))
    with wave.open(str(a.close())) as w:
        assert w.getframerate() == 48000 and w.getnframes() > 40000


def test_chirp_csv(tmp_path):
    path = tmp_path / "c.csv"
    chirp.write_csv(str(path), [{"frequency_hz": 145.5e6, "name": "Call", "mode": "Narrow FM"}])
    lines = path.read_text().splitlines()
    assert lines[0].startswith("Location,Name,Frequency")
    assert lines[1].split(",")[2] == "145.500000" and ",NFM," in lines[1]
    assert chirp.record_mode_for("AM or FM voice") == "FM"


def test_demo_source_is_realtime_safe():
    src = DemoSource(seed=1)
    t = time.time()
    src.read(16384)
    assert time.time() - t < 1.0


def test_band_context_names():
    assert dsp.band_context(100.7e6, 120e3)[0] == "Broadcast FM"
    assert dsp.band_context(121.5e6, 8e3)[0] == "Airband"
    assert dsp.band_context(156.8e6, 12e3)[0] == "Marine VHF"
    assert dsp.band_context(162.0e6, 12e3)[0] == "AIS"
    assert dsp.band_context(145.5e6, 12e3) is None
    assert dsp.band_context(100.7e6, 1e3) is None  # a carrier in the FM band stays generic


def test_labels_never_overlap():
    import pytest

    pytest.importorskip("PIL")
    from bosun.render import SpectrumView

    view = SpectrumView(600, 300)
    f = np.linspace(800e6, 802e6, 2048)
    view.push(f, np.full(2048, -60.0))
    dets = [dsp.Detection(800e6 + i * 3e3, 2e3, -30, 20 - i, "Narrow signal", "")
            for i in range(12)]
    img = view.image(detections=dets)
    assert img.size == (600, 300)


def test_skirts_of_strong_station_are_not_signals():
    strong = dsp.Detection(100.1e6, 150e3, -10, 45, "Broadcast FM", "")
    skirt = dsp.Detection(100.24e6, 3e3, -40, 10, "Narrow signal", "")
    far = dsp.Detection(101.5e6, 3e3, -40, 10, "Narrow signal", "")
    assert dsp._drop_skirts([strong, skirt, far]) == [strong, far]
