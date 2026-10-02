"""Drain ready pipe bytes without hiding lines inside a text-reader buffer."""

from __future__ import annotations

import codecs
import io
import os
from typing import TextIO


class ChildLines:
    """Decode whole lines per ready read, retaining only an unfinished line.

    Selecting a TextIOWrapper then calling readline can prefetch many lines.
    The descriptor is empty afterwards, so the next selector wait strands
    those buffered lines until another child write. Read the descriptor
    directly so every complete line reaches the classifier in this pass.
    """

    def __init__(self, stream: TextIO) -> None:
        self.fd = stream.fileno()
        self.decoder = io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder(stream.encoding)(errors=stream.errors),
            translate=True,
        )
        self.pending = ""
        self.ended = False

    def read(self) -> list[str]:
        chunk = os.read(self.fd, 65536)
        self.ended = not chunk
        self.pending += self.decoder.decode(chunk, final=self.ended)
        parts = self.pending.split("\n")
        lines = [part + "\n" for part in parts[:-1]]
        self.pending = parts[-1]
        if self.ended and self.pending:
            lines.append(self.pending)
            self.pending = ""
        return lines
