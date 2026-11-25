"""SDR receivers shown alongside the radios in the Radio picker and Radios list.

These are receive-only. Picking one and pressing Connect starts it on the
Spectrum tab, where Listen, Record, detection and decoders all work.
"""
from __future__ import annotations

SUFFIX = " (SDR receiver)"

# source: the prefix used by sources.open_source / list_sources.
SDR_RECEIVERS: list[dict] = [
    {"model": "RTL-SDR dongle (RTL2832U)", "vendor": "RTL-SDR", "source": "rtlsdr",
     "bands_mhz": [[24, 1766]],
     "note": "Generic RTL2832U + R820T/R828D sticks. 2.4 MHz live, up to 40 MHz by sweeping."},
    {"model": "RTL-SDR Blog V4", "vendor": "RTL-SDR", "source": "rtlsdr",
     "bands_mhz": [[0.5, 28.8], [24, 1766]],
     "note": "Built-in HF upconverter covers 0.5-28.8 MHz."},
    {"model": "NESDR SMArTee XTR", "vendor": "Nooelec", "source": "rtlsdr",
     "bands_mhz": [[65, 2300]],
     "note": "E4000-based RTL-SDR with extended range."},
    {"model": "RTL-SDR over network (rtl_tcp)", "vendor": "RTL-SDR", "source": "rtl_tcp",
     "bands_mhz": [[24, 1766]],
     "note": "Any RTL-SDR shared with rtl_tcp, including the Android Rtl-sdr driver app."},
    {"model": "HackRF One", "vendor": "Great Scott Gadgets", "source": "hackrf",
     "bands_mhz": [[1, 6000]],
     "note": "Needs the HackRF host tools (hackrf_transfer) installed."},
    {"model": "Airspy R2 / Mini", "vendor": "Airspy", "source": "airspy",
     "bands_mhz": [[24, 1800]], "note": "Needs the Airspy library."},
    {"model": "SoapySDR device (SDRplay, LimeSDR, PlutoSDR, Airspy HF+...)",
     "vendor": "SoapySDR", "source": "soapy", "bands_mhz": [[0.001, 6000]],
     "note": "Any receiver with a SoapySDR module installed; range depends on the device."},
]

MODES = ["WFM", "FM", "AM", "USB", "LSB", "CW"]


def picker_names() -> list[str]:
    return [r["model"] + SUFFIX for r in SDR_RECEIVERS]


def lookup(name: str) -> dict | None:
    """Find a receiver by its picker name (with or without the suffix)."""
    bare = name[:-len(SUFFIX)] if name.endswith(SUFFIX) else name
    return next((r for r in SDR_RECEIVERS if r["model"] == bare), None)


def is_sdr(name: str) -> bool:
    return lookup(name) is not None


def match_source(entry: dict, found: list[str]) -> str | None:
    """Pick the detected source name that belongs to this receiver type."""
    key = entry["source"]
    for name in found:
        if name.startswith(key) or (key == "rtlsdr" and name.startswith("rtl:")):
            return name
    return None


def catalogue() -> list[dict]:
    return [{"model": r["model"], "vendor": r["vendor"], "control": "SDR receiver",
             "bands_mhz": r["bands_mhz"], "modes": MODES, "note": r["note"]}
            for r in SDR_RECEIVERS]
