"""Spectrum maths and automatic signal detection (numpy only)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Plain-language signal types, narrowest first: (max bandwidth Hz, label, hint)
SIGNAL_TYPES = (
    (400, "Carrier / CW", "Morse or an unmodulated carrier"),
    (1_200, "Narrow digital", "FT8, PSK, RTTY or a beacon"),
    (4_000, "Voice (SSB) / data", "Single-sideband voice or HF data"),
    (9_000, "AM voice", "AM broadcast, airband or HF AM"),
    (30_000, "Narrow FM", "Two-way radio, marine, repeaters, telemetry"),
    (120_000, "Wide data", "Digital link or a wider FM signal"),
    (300_000, "Broadcast FM", "FM radio station"),
    (float("inf"), "Wideband", "TV, DAB, LTE, Wi-Fi or other wide digital signal"),
)


@dataclass
class Detection:
    center_hz: float
    bandwidth_hz: float
    peak_db: float
    snr_db: float
    kind: str = ""
    hint: str = ""
    peakiness_db: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.center_hz / 1e6:.4f} MHz  {self.kind}  ({self.snr_db:.0f} dB SNR)"


def classify(bandwidth_hz: float, peakiness_db: float = 0.0,
             resolution_hz: float = 0.0) -> tuple[str, str]:
    """Plain-language guess from occupied bandwidth and spectral shape.

    peakiness_db: peak minus mean power across the signal. A strong central
    carrier (AM) is peaky; FM and digital signals are flat-topped.
    """
    if resolution_hz and bandwidth_hz <= 3 * resolution_hz and resolution_hz > 400:
        return ("Narrow signal",
                "Carrier, CW, SSB or narrow digital: zoom in (smaller span) to tell")
    if 4_000 < bandwidth_hz <= 30_000:
        if peakiness_db != peakiness_db:  # NaN: too coarse to see the carrier
            return ("AM or FM voice",
                    "Two-way, airband, marine or broadcast: zoom in to tell AM from FM")
        if peakiness_db >= 15:
            return "AM voice", "AM broadcast, airband or HF AM (strong carrier)"
        return "Narrow FM", "Two-way radio, marine, repeaters, telemetry"
    for limit, kind, hint in SIGNAL_TYPES:
        if bandwidth_hz <= limit:
            return kind, hint
    return SIGNAL_TYPES[-1][1:]


# Frequency ranges with the same use worldwide (ITU Radio Regulations), used to
# give a more useful name than width alone. (lo Hz, hi Hz, min bw, max bw, kind, hint)
BAND_CONTEXT = (
    (76e6, 108e6, 40e3, 400e3, "Broadcast FM",
     "FM radio station (76-108 MHz broadcast band)"),
    (108e6, 137e6, 2e3, 30e3, "Airband",
     "Aircraft or air traffic control (108-137 MHz, AM voice)"),
    (156e6, 162.05e6, 4e3, 30e3, "Marine VHF",
     "Ship or coast station (156-162 MHz, FM voice)"),
    (161.9e6, 162.05e6, 4e3, 30e3, "AIS",
     "Ship position data (AIS)"),
)


def band_context(center_hz: float, bandwidth_hz: float) -> tuple[str, str] | None:
    """Name a signal by where it is, when width agrees. None if no match."""
    for lo, hi, bw_lo, bw_hi, kind, hint in BAND_CONTEXT[::-1]:
        if lo <= center_hz <= hi and bw_lo <= bandwidth_hz <= bw_hi:
            return kind, hint
    return None


def psd(iq: np.ndarray, rate: float, nfft: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Averaged power spectrum. Returns (offset_hz, power_db), DC centred."""
    iq = np.asarray(iq, dtype=np.complex64)
    if len(iq) < nfft:
        iq = np.pad(iq, (0, nfft - len(iq)))
    nseg = max(1, len(iq) // nfft)
    segs = iq[: nseg * nfft].reshape(nseg, nfft)
    # 4-term Blackman-Harris: very low leakage, so strong signals do not smear.
    k = np.arange(nfft) / nfft
    win = (0.35875 - 0.48829 * np.cos(2 * np.pi * k) + 0.14128 * np.cos(4 * np.pi * k)
           - 0.01168 * np.cos(6 * np.pi * k)).astype(np.float32)
    spec = np.fft.fftshift(np.fft.fft(segs * win, axis=1), axes=1)
    power = np.mean(np.abs(spec) ** 2, axis=0) / (np.sum(win ** 2))
    power_db = 10 * np.log10(power + 1e-20)
    offsets = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / rate))
    return offsets, power_db.astype(np.float32)


def noise_floor(power_db: np.ndarray, window: int | None = None) -> np.ndarray:
    """Local noise floor: 25th percentile in a sliding window (robust to signals).

    The window spans an eighth of the view so wide stations do not lift it.
    """
    n = len(power_db)
    window = max(8, min(window or max(64, n // 8), n))
    pad = window // 2
    padded = np.pad(power_db, (pad, window - pad - 1), mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, window)
    step = max(1, window // 8)
    coarse = np.percentile(view[::step], 25, axis=1)
    return np.interp(np.arange(n), np.arange(0, n, step)[: len(coarse)], coarse).astype(
        np.float32)


def detect(offsets_hz: np.ndarray, power_db: np.ndarray, center_hz: float = 0.0, *,
           threshold_db: float | None = None, floor: np.ndarray | None = None,
           min_bins: int = 2, merge_hz: float | None = None) -> list[Detection]:
    """Find signals standing above the local noise floor.

    threshold_db None picks one automatically from the measured noise spread.
    """
    power_db = np.asarray(power_db, dtype=np.float32)
    floor = noise_floor(power_db) if floor is None else floor
    excess = power_db - floor
    if threshold_db is None:
        quiet = excess[excess < np.percentile(excess, 60)]
        spread = float(np.median(np.abs(quiet - np.median(quiet)))) * 1.4826 if len(quiet) else 1
        threshold_db = max(4.0, 5.0 * max(spread, 0.5))
    above = excess > threshold_db
    bin_hz = float(abs(offsets_hz[1] - offsets_hz[0])) if len(offsets_hz) > 1 else 1.0
    # Bridge small dips inside one signal (FM nulls, SSB gaps).
    merge_bins = max(1, int((merge_hz or 2_000) / bin_hz))

    # Group adjacent bins (bridging small gaps) into signals.
    idx = np.flatnonzero(above)
    out: list[Detection] = []
    if not len(idx):
        return out
    groups, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > merge_bins + 1:
            groups.append((start, prev))
            start = i
        prev = i
    groups.append((start, prev))

    for lo, hi in groups:
        if hi - lo + 1 < min_bins:
            continue
        seg = power_db[lo: hi + 1]
        peak = int(np.argmax(seg)) + lo
        # Occupied bandwidth: the extent above the noise threshold, less the
        # window main lobe (about two bins each side).
        # Trim far skirts of very strong signals: keep bins within 35 dB of the
        # signal's typical (90th percentile) level, not of a carrier spike.
        level = max(float(np.percentile(seg, 90)) - 35.0,
                    float(np.min(floor[lo: hi + 1])) + threshold_db)
        core = np.flatnonzero(seg >= level)
        if len(core):
            lo, hi = lo + int(core[0]), lo + int(core[-1])
            seg = power_db[lo: hi + 1]
        bins = hi - lo + 1
        bw = max(1, bins - 4) * bin_hz
        # Carrier test: a pure carrier line falls away within the main lobe;
        # FM and data spectra are continuous. Needs enough resolution.
        peaky = float("nan")
        if bins >= 20 and 6 * bin_hz < bw / 4:
            side = power_db[[max(peak - 6, 0), min(peak + 6, len(power_db) - 1)]]
            peaky = float(power_db[peak] - np.mean(side))
        weights = 10 ** (seg / 10)
        centroid = float(np.sum(offsets_hz[lo: hi + 1] * weights) / np.sum(weights))
        kind, hint = classify(bw, peaky, bin_hz)
        ctx = band_context(center_hz + centroid, bw) if center_hz + centroid > 1e6 else None
        if ctx is not None:
            kind, hint = ctx
        out.append(Detection(
            center_hz=center_hz + centroid, bandwidth_hz=bw,
            peak_db=float(power_db[peak]), snr_db=float(power_db[peak] - floor[peak]),
            kind=kind, hint=hint, peakiness_db=peaky,
        ))
    return _drop_skirts(sorted(out, key=lambda d: -d.snr_db))


def _drop_skirts(found: list[Detection]) -> list[Detection]:
    """Drop weak 'signals' that are really the edges of a much stronger one."""
    kept: list[Detection] = []
    for d in found:  # strongest first
        shadow = any(
            abs(d.center_hz - k.center_hz) <= k.bandwidth_hz * 1.5 + d.bandwidth_hz
            and k.snr_db - d.snr_db >= 20
            for k in kept)
        if not shadow:
            kept.append(d)
    return kept
