"""Standard output and error carry UTF-8 text on every OS.

Windows Python writes a pipe in the ANSI code page (cp1252 on a stock
runner), so a status line with a non-ASCII glyph such as an arrow raises
UnicodeEncodeError once a harness or test captures the output. Entry points
that print call ``use_utf8_standard_streams`` before writing anything; the
console code page itself is never changed.
"""

from __future__ import annotations

import sys
from typing import TextIO


def use_utf8_standard_streams(*streams: TextIO) -> None:
    """Re-encode the given streams, by default stdout and stderr, as UTF-8."""
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")
