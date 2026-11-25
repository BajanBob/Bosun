"""Crash logging for the windowed desktop app.

Windowed builds have no console, so errors would vanish silently. This writes
every uncaught error, including native crashes (via faulthandler), to a log
file and lets the app show where it is.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import faulthandler
import os
import pathlib
import sys
import threading
import traceback

_log_file = None


def log_dir() -> pathlib.Path:
    base = os.environ.get("LOCALAPPDATA") if sys.platform.startswith("win") else None
    root = pathlib.Path(base) / "Bosun" if base else pathlib.Path.home() / ".config" / "bosun"
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_path() -> pathlib.Path:
    return log_dir() / "bosun.log"


def write(text: str) -> None:
    if _log_file is None:
        return
    try:
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _log_file.write(f"[{stamp}] {text.rstrip()}\n")
        _log_file.flush()
    except Exception:
        pass


def log_exception(exc_type, exc, tb, where: str = "") -> str:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    write(f"ERROR {where}\n{text}")
    return text


def setup() -> pathlib.Path:
    """Start logging. Safe to call more than once."""
    global _log_file
    path = log_path()
    if _log_file is None:
        try:
            if path.exists() and path.stat().st_size > 2_000_000:
                path.replace(path.with_suffix(".old.log"))
            _log_file = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        except OSError:
            return path
        with contextlib.suppress(Exception):
            faulthandler.enable(_log_file, all_threads=True)
        # Windowed builds have no stdout/stderr; send stray output to the log.
        if sys.stdout is None:
            sys.stdout = _log_file
        if sys.stderr is None:
            sys.stderr = _log_file
        sys.excepthook = lambda t, e, tb: log_exception(t, e, tb, "uncaught")
        threading.excepthook = lambda a: log_exception(
            a.exc_type, a.exc_value, a.exc_traceback, f"in thread {a.thread.name if a.thread else '?'}")
        from .version import __version__

        write(f"Bosun {__version__} starting on {sys.platform}, Python {sys.version.split()[0]}"
              f", frozen={getattr(sys, 'frozen', False)}")
    return path
