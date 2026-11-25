"""Config load and logging. Precedence: explicit path, BOSUN_CONFIG, XDG."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import tomllib
from dataclasses import dataclass, field, fields

from .errors import ConfigError

LOG_ENV = "BOSUN_LOG"
CONFIG_ENV = "BOSUN_CONFIG"


@dataclass
class Config:
    model: str | None = None
    port: str | None = None
    tcp: str | None = None
    baud: int | None = None
    audio_codec: str | None = None
    sdr: str | None = None
    memory_bank: str | None = None
    scan_dwell: float = 0.6
    scan_resume: str = "time"
    scan_resume_after: float = 3.0
    log_level: str = "WARNING"
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("scan_dwell", "scan_resume_after"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be positive")
        if self.scan_resume not in ("time", "stop", "off"):
            raise ConfigError(f"unknown scan_resume {self.scan_resume!r}")


def _default_path() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = pathlib.Path(base) if base else pathlib.Path.home() / ".config"
    return root / "bosun" / "config.json"


def resolve_path(explicit=None):
    if explicit:
        return pathlib.Path(explicit)
    env = os.environ.get(CONFIG_ENV)
    if env:
        return pathlib.Path(env)
    candidate = _default_path()
    return candidate if candidate.exists() else None


def _read(path: pathlib.Path) -> dict:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        if path.suffix == ".toml":
            return tomllib.loads(raw.decode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc


def _coerce(data: dict) -> dict:
    known = {f.name for f in fields(Config)}
    out: dict = {}
    for key, value in data.items():
        if key in known and key != "extra":
            out[key] = value
        else:
            out.setdefault("extra", {})[key] = value
    return out


def load(path=None) -> Config:
    resolved = resolve_path(path)
    data: dict = {}
    if resolved is not None:
        if not resolved.exists():
            raise ConfigError(f"config not found: {resolved}")
        data = _coerce(_read(resolved))
    for key, env in (
        ("model", "BOSUN_MODEL"), ("port", "BOSUN_PORT"),
        ("tcp", "BOSUN_TCP"), ("sdr", "BOSUN_SDR"), ("log_level", LOG_ENV),
    ):
        if os.environ.get(env):
            data[key] = os.environ[env]
    if os.environ.get("BOSUN_BAUD"):
        data["baud"] = int(os.environ["BOSUN_BAUD"])
    return Config(**data)


def setup_logging(config: Config | None = None) -> logging.Logger:
    name = os.environ.get(LOG_ENV) or (config.log_level if config else "WARNING")
    logging.basicConfig(
        level=getattr(logging, name.upper(), logging.WARNING),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return logging.getLogger("bosun")


def default_bank_path(model: str) -> pathlib.Path:
    return _default_path().parent / "memory" / f"{model.replace('/', '-')}.json"
