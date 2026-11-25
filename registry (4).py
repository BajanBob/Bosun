from ..errors import RadioNotFound
from .drivers import AR8200, AR8600, FT991A, IC9100, IC9700

DRIVERS = {d.model: d for d in (IC9100, IC9700, FT991A, AR8200, AR8600)}


def get(model: str):
    try:
        return DRIVERS[model]
    except KeyError:
        raise RadioNotFound(f"no driver for {model!r}; known: {', '.join(DRIVERS)}") from None


def catalogue() -> list[dict]:
    return [
        {
            "model": m.model, "vendor": m.vendor, "caps": m.caps.name,
            "bands_mhz": [[lo / 1e6, hi / 1e6] for lo, hi in m.bands],
            "modes": list(m.modes), "max_channel": m.max_channel,
        }
        for m in DRIVERS.values()
    ]
