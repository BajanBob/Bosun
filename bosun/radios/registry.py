from ..errors import RadioNotFound
from . import drivers as d
from .profile import load_profiles, make_driver

BUILTIN = (
    d.IC9100, d.IC9700, d.IC7300, d.IC705, d.IC7610, d.IC7100, d.ICR8600, d.ICR75,
    d.FT991A, d.FT710, d.FTDX10, d.FTDX101D, d.FT891,
    d.TS590SG, d.TS890S, d.TS480, d.TS2000,
    d.AR8200, d.AR8600, d.AR5000, d.ARDV1,
    d.RadtelRT950Pro,
)

DRIVERS: dict = {}


def reload() -> dict:
    """Rebuild the driver table, picking up edited command profiles."""
    DRIVERS.clear()
    DRIVERS.update({m.model: m for m in BUILTIN})
    for model, (profile, path) in load_profiles().items():
        if model not in DRIVERS:
            try:
                DRIVERS[model] = make_driver(profile, str(path))
            except Exception:
                continue
    return DRIVERS


reload()


def get(model: str):
    try:
        return DRIVERS[model]
    except KeyError:
        raise RadioNotFound(f"no driver for {model!r}; known: {', '.join(DRIVERS)}") from None


def vendors() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in DRIVERS.values():
        out.setdefault(m.vendor, []).append(m.model)
    return {v: sorted(ms) for v, ms in sorted(out.items())}


def describe(model: str) -> str:
    m = get(model)
    if getattr(m, "audio_only", False):
        return ("No computer control on this radio. Bosun records its audio through your "
                "sound input and exports channel lists for CHIRP / Radtel CPS.")
    if getattr(m, "needs_setup", False):
        return ("This radio's command set is only in the maker's remote-control manual. "
                "Fill in its command profile once (Setup wizard, step 2) and Bosun will "
                "use it.")
    return f"Direct control over {m.transport_kind}, default {m.default_baud} baud."


def catalogue() -> list[dict]:
    return [
        {
            "model": m.model, "vendor": m.vendor, "caps": m.caps.name,
            "bands_mhz": [[lo / 1e6, hi / 1e6] for lo, hi in m.bands],
            "modes": list(m.modes), "max_channel": m.max_channel,
            "control": ("audio only" if getattr(m, "audio_only", False)
                        else "profile (needs setup)" if getattr(m, "needs_setup", False)
                        else "profile" if hasattr(m, "profile_path") else "built in"),
        }
        for m in DRIVERS.values()
    ]
