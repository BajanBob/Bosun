"""Hover tips: plain-language help that appears when the pointer rests on a control."""

from __future__ import annotations

import tkinter as tk

TIPS = {
    # connection
    "radio": "Pick your radio model. Not sure? Open Setup > Setup wizard and it will walk "
             "you through it.",
    "link_serial": "Use this when the radio is plugged in with a USB or serial cable.",
    "link_tcp": "Use this when the radio is reached over the network, e.g. a ser2net box, "
                "a LAN-to-serial adapter or a Wi-Fi bridge.",
    "port": "The COM port (Windows) or /dev/tty... device (Linux) your radio cable created. "
            "Unplug and replug the cable, then press Refresh to see which one appears.",
    "refresh": "Look again for USB / serial ports.",
    "baud": "Data speed. It must match the CAT / CI-V baud rate set in your radio's menu. "
            "Bosun fills in the usual value for your model.",
    "host": "IP address or name of the network adapter attached to the radio.",
    "tcp_port": "TCP port number set on the network adapter (often 4000-4532).",
    "connect": "Open the link to the radio and read its frequency and mode.",
    # control
    "freq": "Type a frequency in MHz, e.g. 145.500 or 7.1. Press Enter or Tune.",
    "mode": "Demodulation mode: FM for two-way radio, AM for airband, USB/LSB for HF voice, "
            "CW for Morse.",
    "tune": "Send the frequency and mode to the radio.",
    "af": "Volume (audio gain). Applied when you let go of the slider.",
    "rf": "RF gain: turn down to calm strong nearby signals, up for weak ones.",
    "squelch": "Mutes the speaker until a signal is stronger than this level. Also used by "
               "Scan to decide what counts as a hit.",
    "status": "Ask the radio for its current frequency and mode.",
    # scan
    "scan_start": "Lowest frequency to scan, in MHz.",
    "scan_stop": "Highest frequency to scan, in MHz.",
    "scan_step": "Gap between steps in kHz: 12.5 or 25 for VHF/UHF FM, 5 for HF, 8.33 for "
                 "European airband.",
    "scan_dwell": "Seconds to listen on each step before moving on.",
    "scan_go": "Start or stop scanning with the radio. Needs a radio that can report squelch.",
    "hits": "Frequencies where the squelch opened. Double-click one to tune to it.",
    # spectrum
    "source": "Where the spectrum comes from: an RTL-SDR or other SDR, an rtl_tcp server "
              "(type rtl_tcp:host:port, e.g. a Raspberry Pi running rtl_tcp), or the Demo, "
              "which simulates a busy band so you can try everything without hardware.",
    "find_sdrs": "Search for plugged-in SDRs (RTL-SDR, SoapySDR devices, Airspy).",
    "center": "Centre of the view in MHz. Double-click the waterfall to re-centre there.",
    "span": "How wide a slice to show. Narrower spans show more detail (and tell AM from FM).",
    "gain": "SDR gain in dB. Raise it for weak signals; lower it if the waterfall turns "
            "bright everywhere (overload).",
    "run": "Start or stop the live spectrum and waterfall.",
    "auto_detect": "Automatic signal detection: Bosun finds signals above the noise and "
                   "labels what they probably are.",
    "cognitive": "Cognitive receiver: learns the band over time, follows the real noise "
                 "floor, keeps a log of every signal and how busy it is, and flags new ones in "
                 "pink.",
    "sensitivity": "How weak a signal must be before Bosun ignores it. Higher finds weaker "
                   "signals but may mark noise.",
    "capture": "Save the spectrum and waterfall as a PNG picture in 'Bosun Recordings'.",
    "rec_iq": "Record raw IQ from the SDR (SigMF format, opens in GNU Radio, Inspectrum, "
              "SDR# and other tools). Files get large quickly.",
    "rec_audio": "Record the selected signal as listenable audio (WAV). Click a signal on "
                 "the waterfall first, and pick its mode.",
    "rec_mode": "How to demodulate the selected signal for audio recording.",
    "sweep_start": "Sweep: lowest frequency in MHz. Sweeps cover ranges wider than one view.",
    "sweep_stop": "Sweep: highest frequency in MHz.",
    "sweep": "Step the SDR across the whole range, stitch it into one picture and log every "
             "signal found.",
    "canvas": "Hover to read frequency and level. Click to select a signal (and tune a "
              "connected radio). Double-click to re-centre.",
    "signals": "Every signal found. Double-click to select it; pink means newly heard.",
    "export_csv": "Save the signal log as a spreadsheet (CSV).",
    "export_chirp": "Save signals as a channel list in CHIRP CSV format, to load into "
                    "handhelds and mobiles such as the Radtel RT-950 Pro.",
    # audio
    "audio_in": "The sound input carrying the radio's audio: the radio's own USB audio "
                "device, or line-in / mic-in from its speaker or data jack.",
    "audio_rec": "Start or stop recording that input to a WAV file in 'Bosun Recordings'.",
    "open_folder": "Open the folder where recordings and captures are saved.",
    # devices
    "probe": "List serial ports, known USB-serial cables, sound devices and SDRs.",
}


class Tooltip:
    """Shows a small tip after the pointer rests on a widget."""

    enabled = True
    DELAY_MS = 600

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget, self.text = widget, text
        self._after = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        if Tooltip.enabled and self.text:
            self._after = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self._after is not None:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self) -> None:
        if self._tip is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self.text, justify="left", wraplength=320, background="#fffbe6",
                 foreground="#222", relief="solid", borderwidth=1, padx=8, pady=5).pack()
        self._tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def tip(widget: tk.Widget, key: str) -> tk.Widget:
    Tooltip(widget, TIPS.get(key, key))
    return widget
