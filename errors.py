"""Exception hierarchy rooted at BosunError."""


class BosunError(Exception):
    """Base for all bosun errors."""


class TransportError(BosunError):
    """Transport could not open, write, or read."""


class ProtocolError(BosunError):
    """Malformed frame, bad reply, or reply timeout."""


class UnsupportedCapability(BosunError):
    """The radio does not implement the operation."""

    def __init__(self, radio: str, cap: str) -> None:
        super().__init__(f"{radio} does not support '{cap}'")
        self.radio, self.cap = radio, cap


class RadioNotFound(BosunError):
    """No driver under that model name."""


class SDRUnavailable(BosunError):
    """Backend or native library absent."""


class CodecError(BosunError):
    """Audio codec could not be opened."""


class OutOfRange(BosunError):
    """Value outside the radio's band plan or channel range."""


class MemoryError_(BosunError):
    """Channel invalid, empty, or bank unwritable."""


class ScanError(BosunError):
    """Scan could not start or stopped abnormally."""


class ConfigError(BosunError):
    """Config missing, malformed, or inconsistent."""
