import pytest

from bosun.errors import MemoryError_
from bosun.memory import Memory, MemoryBank


@pytest.fixture
def bank(tmp_path):
    return MemoryBank.open("IC-9700", tmp_path / "b.json", modes={"FM", "USB"})


def test_put_get(bank):
    bank.put(Memory(3, 145_500_000, "FM", "CALL"))
    assert bank.get(3).frequency == 145_500_000


def test_persistence(bank, tmp_path):
    bank.put(Memory(3, 145_500_000, "FM", "CALL"))
    bank.save()
    again = MemoryBank.open("IC-9700", tmp_path / "b.json", modes={"FM", "USB"})
    assert len(again) == 1 and again.get(3).label == "CALL"


def test_rejects_bad_channel(bank):
    with pytest.raises(MemoryError_):
        bank.put(Memory(200, 145_000_000, "FM"))


def test_rejects_bad_mode(bank):
    with pytest.raises(MemoryError_):
        bank.put(Memory(1, 145_000_000, "DV"))


def test_scan_order_skips(bank):
    bank.put(Memory(1, 145_000_000, "FM"))
    bank.put(Memory(2, 145_100_000, "FM", skip=True))
    bank.put(Memory(3, 145_200_000, "FM"))
    assert [m.channel for m in bank.scan_order()] == [1, 3]


def test_duplicates(bank):
    bank.put(Memory(1, 145_000_000, "FM"))
    bank.put(Memory(2, 145_000_000, "FM"))
    assert bank.duplicates() == [(1, 2)]


def test_missing_channel(bank):
    with pytest.raises(MemoryError_):
        bank.get(9)
