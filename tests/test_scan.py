import pytest

from bosun.errors import ScanError
from bosun.memory import Memory, MemoryBank
from bosun.scan import ScanEngine


def test_range_order(fake_radio):
    engine = ScanEngine(fake_radio, mode="range", dwell=0.001, max_cycles=1)
    engine.use_range(100_000_000, 100_300_000, 100_000)
    engine.run()
    assert fake_radio.frequencies == [
        100_000_000, 100_100_000, 100_200_000, 100_300_000]


def test_list_uses_bank(fake_radio, tmp_path):
    bank = MemoryBank("IC-9700", tmp_path / "b.json")
    bank.put(Memory(1, 145_000_000, "FM"))
    bank.put(Memory(2, 145_200_000, "FM"))
    engine = ScanEngine(fake_radio, dwell=0.001, max_cycles=1)
    engine.use_bank(bank)
    engine.run()
    assert fake_radio.frequencies == [145_000_000, 145_200_000]


def test_lockout(fake_radio):
    engine = ScanEngine(fake_radio, mode="range", dwell=0.001, max_cycles=1)
    engine.use_range(100_000_000, 100_200_000, 100_000)
    engine.lockout(100_100_000)
    engine.run()
    assert 100_100_000 not in fake_radio.frequencies


def test_detector_hit(fake_radio):
    hits = []
    fake_radio.squelch = True
    engine = ScanEngine(
        fake_radio, mode="range", dwell=0.001, resume="off", max_cycles=1,
        detector=fake_radio.squelch_open, on_hit=hits.append)
    engine.use_range(100_000_000, 100_000_000, 100_000)
    engine.run()
    assert hits == [100_000_000] and engine.stats.hits == 1


def test_resume_stop(fake_radio):
    fake_radio.squelch = True
    engine = ScanEngine(
        fake_radio, mode="range", dwell=0.001, resume="stop",
        detector=fake_radio.squelch_open)
    engine.use_range(100_000_000, 100_900_000, 100_000)
    engine.run()
    assert len(fake_radio.frequencies) == 1


def test_bad_dwell():
    with pytest.raises(ScanError):
        ScanEngine(object(), dwell=0)


def test_range_validation(fake_radio):
    with pytest.raises(ScanError):
        ScanEngine(fake_radio, mode="range").use_range(200, 100, 10)


def test_detector_errors_do_not_kill_scan():
    from bosun.scan import ScanEngine

    class Radio:
        def set_frequency(self, hz):
            pass

    def broken():
        raise RuntimeError("no reply")

    engine = ScanEngine(Radio(), mode="range", dwell=0.001, detector=broken, max_cycles=2)
    engine.use_range(1e6, 1.002e6, 1e3)
    engine.run()
    assert engine.stats.cycles == 2 and engine.stats.errors == 6
