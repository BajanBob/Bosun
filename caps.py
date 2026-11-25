"""Capability flags. Drivers declare only what they can do."""

from enum import Flag, auto


class Cap(Flag):
    NONE = 0
    RX = auto()
    TX = auto()
    TUNE = auto()
    MODE = auto()
    FILTER = auto()
    AGC = auto()
    SQUELCH = auto()
    ATTENUATOR = auto()
    PREAMP = auto()
    RF_GAIN = auto()
    AF_GAIN = auto()
    PTT = auto()
    VFO = auto()
    MEMORY = auto()
    SCAN = auto()
    USB_AUDIO = auto()
    USB_SERIAL = auto()
    IQ_OUTPUT = auto()
    DV = auto()
    SPECTRUM = auto()

    def has(self, other: "Cap") -> bool:
        return bool(self & other)
