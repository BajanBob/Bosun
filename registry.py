from __future__ import annotations

from ..errors import SDRUnavailable
from .drivers import BACKENDS


def available() -> dict[str, list[str]]:
    out = {}
    for key, cls in BACKENDS.items():
        try:
            devs = cls.probe()
        except Exception:
            devs = []
        if devs:
            out[key] = devs
    return out


def open_backend(spec: str):
    if ":" not in spec:
        raise SDRUnavailable(f"spec must be 'driver:device', got {spec!r}")
    key, device = spec.split(":", 1)
    if key not in BACKENDS:
        raise SDRUnavailable(f"unknown backend {key!r}")
    backend = BACKENDS[key]()
    backend.open(f"{key}:{device}")
    return backend
