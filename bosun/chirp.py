"""Channel lists in CHIRP's generic CSV format (import with File > Import).

Works for any radio CHIRP supports, and the columns are easy to retype into a
maker's own programming software (e.g. Radtel CPS).
"""

from __future__ import annotations

import csv

COLUMNS = ["Location", "Name", "Frequency", "Duplex", "Offset", "Tone", "rToneFreq",
           "cToneFreq", "DtcsCode", "DtcsPolarity", "RxDtcsCode", "CrossMode", "Mode",
           "TStep", "Skip", "Power", "Comment", "URCALL", "RPT1CALL", "RPT2CALL",
           "DVCODE"]

CHIRP_MODES = {"FM": "FM", "NFM": "NFM", "FM-N": "NFM", "WFM": "WFM", "AM": "AM",
               "USB": "USB", "LSB": "LSB", "CW": "CW", "DV": "DV"}


# Bosun's signal types (bosun.dsp) to CHIRP modes.
KIND_MODES = {
    "Carrier / CW": "CW", "Narrow digital": "USB", "Voice (SSB) / data": "USB",
    "Narrow signal": "USB", "AM voice": "AM", "AM or FM voice": "NFM",
    "Narrow FM": "NFM", "Wide data": "FM", "Broadcast FM": "WFM", "Wideband": "WFM",
}


def record_mode_for(kind: str) -> str:
    """Demodulator mode for recording a detected signal type."""
    return {"NFM": "FM", "FM": "FM"}.get(mode_for(kind), mode_for(kind))


def mode_for(kind_or_mode: str) -> str:
    if kind_or_mode in KIND_MODES:
        return KIND_MODES[kind_or_mode]
    text = (kind_or_mode or "").upper()
    if text in CHIRP_MODES:
        return CHIRP_MODES[text]
    if "BROADCAST" in text:
        return "WFM"
    if "AM" in text:
        return "AM"
    if "SSB" in text:
        return "USB"
    if "CW" in text or "CARRIER" in text:
        return "CW"
    return "NFM"


def write_csv(path: str, channels: list[dict], start: int = 1) -> int:
    """channels: dicts with frequency_hz, name, mode, comment (optional)."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for i, ch in enumerate(channels, start=start):
            w.writerow([
                i, (ch.get("name") or "")[:16], f"{ch['frequency_hz'] / 1e6:.6f}", "",
                "0.000000", "", "88.5", "88.5", "023", "NN", "023", "Tone->Tone",
                mode_for(ch.get("mode", "")), "12.50", "", "",
                ch.get("comment", ""), "", "", "", "",
            ])
    return len(channels)
