import numpy as np
import pytest

from bosun import atv


@pytest.mark.parametrize("mode", ["FM", "AM"])
@pytest.mark.parametrize("std", ["PAL", "NTSC"])
def test_decodes_test_pattern(mode, std):
    s = atv.STANDARDS[std]
    src = atv.ATVTestSource(8e6, s, mode, noise=0.1)
    dec = atv.ATVDecoder(8e6, s, mode)
    fields = []
    for _ in range(12):
        fields += dec.process(src.read(int(8e6 / 25)))
    assert len(fields) >= 4 and dec.lock > 0.9
    bars = fields[-1][20:200].mean(axis=0)
    # eight grey bars, bright to dark, left to right
    levels = [bars[int((i + 0.5) * len(bars) / 8)] for i in range(8)]
    assert all(a > b for a, b in zip(levels[1:], levels[2:], strict=False))
    assert levels[1] - levels[7] > 100


def test_inverted_transmitter_needs_invert():
    src = atv.ATVTestSource(8e6, atv.PAL, "FM", noise=0.05)
    iq = np.concatenate([src.read(int(8e6 / 25)) for _ in range(8)])
    inverted = np.conj(iq)  # FM spectrum flipped
    plain = atv.ATVDecoder(8e6, atv.PAL, "FM")
    fixed = atv.ATVDecoder(8e6, atv.PAL, "FM", invert=True)
    assert not plain.process(inverted) or plain.lock < 0.5
    assert fixed.process(inverted) and fixed.lock > 0.9


def test_fpv_channels():
    assert atv.FPV_CHANNELS["5.8G Raceband R1"] == 5658
    assert len([k for k in atv.FPV_CHANNELS if "Raceband" in k]) == 8
