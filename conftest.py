import pytest

from bosun.transport import NullTransport


class FakeRadio:
    model = "FAKE"
    max_channel = 99

    def __init__(self) -> None:
        self.frequencies: list[float] = []
        self.squelch = False
        self.transport = NullTransport()

    def set_frequency(self, hz: float) -> None:
        self.frequencies.append(hz)

    def squelch_open(self):
        return self.squelch

    def connect(self):
        self.transport.open()

    def disconnect(self):
        self.transport.close()


@pytest.fixture
def fake_radio():
    return FakeRadio()
