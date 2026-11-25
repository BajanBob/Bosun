"""Radios driven by an editable command profile (JSON).

Used for radios whose remote-control command set is published only in the
maker's own manuals (Barrett, Harris and others). The profile lists command
templates; any command left empty is reported as "not set up yet" instead of
being guessed.

Templates may use {hz}, {khz}, {mhz} (frequency), {mode} (the radio's own mode
code) and {pct} / {val255} (levels, 0-100 or 0-255).
"""

from __future__ import annotations

import json
import pathlib
import re

from ..caps import Cap
from ..errors import ConfigError, ProtocolError
from .base import RadioBase
from .protocols import LineCodec

BUILTIN_DIR = pathlib.Path(__file__).with_name("command_profiles")

COMMAND_KEYS = {
    "set_frequency": Cap.TUNE, "get_frequency": Cap.TUNE,
    "set_mode": Cap.MODE, "get_mode": Cap.MODE,
    "squelch_open": Cap.SQUELCH, "set_squelch": Cap.SQUELCH,
    "set_af_gain": Cap.AF_GAIN, "set_rf_gain": Cap.RF_GAIN,
    "ptt_on": Cap.PTT, "ptt_off": Cap.PTT,
}


def user_dir() -> pathlib.Path:
    from ..config import _default_path

    return _default_path().parent / "radio_profiles"


def _unescape(text: str) -> bytes:
    return text.encode("utf-8").decode("unicode_escape").encode("latin-1")


class ProfileRadio(RadioBase):
    profile: dict = {}
    profile_path: str = ""

    def __init__(self, transport, **kw) -> None:
        term = _unescape(self.profile.get("terminator", "\\r"))
        super().__init__(transport, LineCodec(term), **kw)
        self._cmd = self.profile.get("commands", {})

    # -- helpers
    def _template(self, key: str) -> str:
        tpl = (self._cmd.get(key) or "").strip()
        if not tpl:
            raise ConfigError(
                f"{self.model}: the '{key}' command is not set up yet. Open the Setup "
                f"wizard, step 2 (Command profile), and copy it from the radio's "
                f"remote-control manual.")
        return tpl

    def _fmt(self, key: str, **values) -> bytes:
        try:
            return _unescape(self._template(key).format(**values))
        except (KeyError, ValueError, IndexError) as exc:
            raise ConfigError(f"{self.model}: bad template for {key}: {exc}") from exc

    def _reply_value(self, key: str, reply_key: str) -> str:
        self._send(self._fmt(key))
        frames = self._query_raw()
        pattern = self._cmd.get(reply_key) or r"([-+]?[0-9.]+)"
        for frame in frames:
            m = re.search(pattern, frame.decode("latin-1"))
            if m:
                return m.group(1) if m.groups() else m.group(0)
        raise ProtocolError(f"{self.model}: no reply matched {pattern!r}")

    def _query_raw(self) -> list[bytes]:
        frames: list[bytes] = []
        buffer = b""
        for _ in range(16):
            chunk = self._t.read(256, self._timeout)
            if not chunk:
                break
            got, buffer = self._codec.split(buffer + chunk)
            frames.extend(got)
        if not frames:
            raise ProtocolError(f"{self.model}: no reply")
        return frames

    @staticmethod
    def _levels(pct: float) -> dict:
        pct = max(0.0, min(100.0, float(pct)))
        return {"pct": round(pct), "val255": round(pct * 2.55)}

    # -- driver hooks
    def _do_set_frequency(self, hz: float) -> None:
        self._send(self._fmt("set_frequency", hz=int(round(hz)), khz=hz / 1e3, mhz=hz / 1e6))

    def _do_get_frequency(self) -> float:
        value = float(self._reply_value("get_frequency", "frequency_reply"))
        unit = self.profile.get("frequency_unit", "hz").lower()
        return value * {"hz": 1, "khz": 1e3, "mhz": 1e6}.get(unit, 1)

    def _do_set_mode(self, code) -> None:
        self._send(self._fmt("set_mode", mode=code))

    def _do_get_mode(self):
        return self._reply_value("get_mode", "mode_reply")

    def _do_squelch_open(self):
        self._send(self._fmt("squelch_open"))
        pattern = self._cmd.get("squelch_open_reply") or "1"
        return any(re.search(pattern, f.decode("latin-1")) for f in self._query_raw())

    def _do_ptt(self, on: bool) -> None:
        self._send(self._fmt("ptt_on" if on else "ptt_off"))

    def set_squelch(self, pct: float) -> None:
        self.require(Cap.SQUELCH)
        self._send(self._fmt("set_squelch", **self._levels(pct)))

    def set_af_gain(self, pct: float) -> None:
        self.require(Cap.AF_GAIN)
        self._send(self._fmt("set_af_gain", **self._levels(pct)))

    def set_rf_gain(self, pct: float) -> None:
        self.require(Cap.RF_GAIN)
        self._send(self._fmt("set_rf_gain", **self._levels(pct)))

    def status(self) -> dict:
        out = super().status()
        missing = [k for k in ("set_frequency", "get_frequency") if not self._cmd.get(k)]
        if missing:
            out["note"] = f"Profile not set up yet: edit {self.profile_path}"
        return out


def configured(profile: dict) -> bool:
    return bool((profile.get("commands") or {}).get("set_frequency"))


def make_driver(profile: dict, path: str = "") -> type:
    if not profile.get("model"):
        raise ConfigError(f"profile {path or '?'} has no model name")
    caps = Cap.RX | Cap.USB_SERIAL
    for key, cap in COMMAND_KEYS.items():
        if (profile.get("commands") or {}).get(key):
            caps |= cap
    if not profile.get("receive_only") and (profile.get("commands") or {}).get("ptt_on"):
        caps |= Cap.TX
    # Tuning is offered even before setup so the user gets a clear message.
    caps |= Cap.TUNE | Cap.MODE
    name = re.sub(r"\W", "", profile["model"]) or "Profile"
    return type(name, (ProfileRadio,), {
        "model": profile["model"],
        "vendor": profile.get("vendor", "Other"),
        "caps": caps,
        "default_baud": int(profile.get("baud", 9600)),
        "modes": dict(profile.get("modes") or {"USB": "USB", "LSB": "LSB", "AM": "AM"}),
        "bands": [(lo * 1e6, hi * 1e6) for lo, hi in profile.get("bands_mhz", [])],
        "profile": profile,
        "profile_path": path,
        "needs_setup": not configured(profile),
        "notes": profile.get("notes", ""),
    })


def load_profiles() -> dict[str, tuple[dict, pathlib.Path]]:
    """Built-in templates, overridden by the user's copies of the same model."""
    found: dict[str, tuple[dict, pathlib.Path]] = {}
    for folder in (BUILTIN_DIR, user_dir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("model"):
                found[data["model"]] = (data, path)
    return found


def save_user_profile(profile: dict) -> pathlib.Path:
    if not profile.get("model"):
        raise ConfigError("profile needs a model name")
    folder = user_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (re.sub(r"[^A-Za-z0-9_-]+", "_", profile["model"]).strip("_") + ".json")
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return path
