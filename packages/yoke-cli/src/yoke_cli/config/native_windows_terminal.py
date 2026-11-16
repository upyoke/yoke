"""UTF-8 setup/status output and conservative Windows terminal color detection."""

from __future__ import annotations

import os
import sys


def supports_color(stream) -> bool:
    if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
        return False
    if not stream.isatty():
        return False
    if os.environ.get("WT_SESSION") or os.environ.get("ANSICON"):
        return True
    try:
        import ctypes
        import msvcrt

        mode = ctypes.c_ulong()
        handle = ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno()))
        return bool(
            ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            and mode.value & 4
        )
    except (ImportError, AttributeError, OSError, ValueError):
        return False


def configure() -> None:
    """Change this process's streams only; never change the console code page."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    if not supports_color(sys.stdout):
        os.environ["NO_COLOR"] = "1"
