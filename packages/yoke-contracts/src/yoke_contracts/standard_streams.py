"""Explicit UTF-8 encoding for CLI input and output streams.

Windows Python writes a pipe in the ANSI code page (cp1252 on a stock
runner), so a status line with a non-ASCII glyph such as an arrow raises
UnicodeEncodeError once a harness or test captures the output. Entry points
that print call ``use_utf8_standard_streams`` before writing anything; the
console code page itself is never changed.
"""

from __future__ import annotations

import codecs
import os
import sys
from collections.abc import Mapping
from encodings import utf_8_sig
from typing import TextIO


UTF8_BOM_ENCODING = "yoke_utf_8_sig"


class _Utf8BomDecoder(utf_8_sig.IncrementalDecoder):
    def _buffer_decode(self, data, errors, final):
        # Python's utf-8-sig stream decoder treats a partial BOM at EOF as
        # empty input. Pass it to strict UTF-8 decoding to report the bad bytes.
        if final and self.first and 0 < len(data) < 3 and codecs.BOM_UTF8.startswith(data):
            return codecs.utf_8_decode(data, errors, final)
        return super()._buffer_decode(data, errors, final)


def _lookup_utf8_bom(encoding: str) -> codecs.CodecInfo | None:
    if encoding != UTF8_BOM_ENCODING:
        return None
    codec = utf_8_sig.getregentry()
    codec.incrementaldecoder = _Utf8BomDecoder
    return codec


codecs.register(_lookup_utf8_bom)


class InvalidStdinEncoding(RuntimeError):
    """Stdin contained bytes that could not be decoded as UTF-8."""


def _refuse_invalid_stdin(error: UnicodeError) -> tuple[str, int]:
    # This is a CLI input refusal, so adapters handling ValueError for their
    # own fields should let it reach the entry point unchanged.
    raise InvalidStdinEncoding("stdin_invalid_utf8: stdin must contain UTF-8 text") from error


def use_utf8_stdin() -> None:
    """Read text from stdin as UTF-8, dropping a leading BOM when present."""
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure:
        codecs.register_error("yoke_invalid_stdin_encoding", _refuse_invalid_stdin)
        reconfigure(encoding=UTF8_BOM_ENCODING, errors="yoke_invalid_stdin_encoding")


def use_utf8_standard_streams(*streams: TextIO) -> None:
    """Re-encode the given streams, by default stdout and stderr, as UTF-8."""
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def utf8_python_child_env(
    env: Mapping[str, str] | None = None,
) -> Mapping[str, str] | None:
    """Make redirected Python stdout and stderr UTF-8 from startup on Windows."""
    if sys.platform != "win32":
        return env
    return {**(os.environ if env is None else env), "PYTHONIOENCODING": "utf-8"}
