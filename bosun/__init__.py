"""Bosun — control layer for the ARGUS-Q receiver family."""

from .caps import Cap
from .errors import (
    BosunError,
    CodecError,
    ConfigError,
    MemoryError_,
    OutOfRange,
    ProtocolError,
    RadioNotFound,
    ScanError,
    SDRUnavailable,
    TransportError,
    UnsupportedCapability,
)
from .version import __version__

__all__ = [
    "Cap", "BosunError", "CodecError", "ConfigError", "MemoryError_",
    "OutOfRange", "ProtocolError", "RadioNotFound", "ScanError",
    "SDRUnavailable", "TransportError", "UnsupportedCapability", "__version__",
]
