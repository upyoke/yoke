"""Split a byte stream into JSONL records, each decoded under a bound.

Every reader of a growing harness artifact meets the same two problems:
where one record ends, and how much of it may be held in memory while it
is decoded. This module answers both once. Splitting is a newline search
over each chunk; decoding is delegated to a per-record decoder, either the
general buffered one here or a projecting decoder a caller supplies.

A decoder states three things about the record it is holding:
``record_bytes`` so the stream can advance an offset over it,
``peak_retained_bytes`` so a caller can prove the read cost its bounds
rather than the artifact's size, and ``unrecoverable`` so a record whose
content could not be read is reported as a gap instead of passing as an
absence.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional


def parse_row(record: bytes) -> Optional[dict]:
    """Return one JSON object, or ``None`` for anything else."""
    if not record.strip():
        return None
    try:
        parsed = json.loads(record)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


class BufferedJsonRecord:
    """The general bounded decoder used when no projection is selected."""

    def __init__(self, record_limit: int) -> None:
        self._limit = record_limit
        self._buffer = bytearray()
        self.record_bytes = 0
        self.peak_retained_bytes = 0
        self.unrecoverable = False
        self.full_decodes = 0

    def feed(self, data: bytes | memoryview) -> None:
        self.record_bytes += len(data)
        if self.unrecoverable:
            return
        room = self._limit + 1 - len(self._buffer)
        if room > 0:
            self._buffer.extend(data[:room])
            self.peak_retained_bytes = max(self.peak_retained_bytes, len(self._buffer))
        if self.record_bytes > self._limit:
            self._buffer.clear()
            self.unrecoverable = True

    def finish(self) -> Optional[dict]:
        if self.unrecoverable or not self._buffer.strip():
            return None
        self.full_decodes = 1
        return parse_row(bytes(self._buffer))


class RecordStream:
    """Split a byte stream while each decoder retains only bounded state."""

    def __init__(
        self,
        consume: Callable[[dict], Any],
        *,
        record_limit: int,
        record_factory: Optional[Callable[[int], Any]] = None,
        skip_record: bool = False,
        on_unrecoverable: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._consume = consume
        self._record_limit = record_limit
        self._record_factory = record_factory
        self._on_unrecoverable = on_unrecoverable
        self._decoder = self._new_decoder()
        self._skipping = skip_record
        self._skipped_bytes = 0
        self.consumed = 0
        self.oversized = False
        self.records_decoded = 0
        self.peak_retained_bytes = 0

    @property
    def inside_record(self) -> bool:
        """True when bytes of a record have arrived without its newline.

        A scan that stops here would stop halfway through one record, so
        this is what tells a caller to keep reading to the record's end
        rather than yield between records.
        """
        return self._skipping or bool(self._decoder.record_bytes)

    @property
    def current_unrecoverable(self) -> bool:
        return bool(self._decoder.unrecoverable) if not self._skipping else True

    def _new_decoder(self) -> Any:
        if self._record_factory is not None:
            return self._record_factory(self._record_limit)
        return BufferedJsonRecord(self._record_limit)

    def feed(self, chunk: bytes) -> None:
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            end = len(chunk) if newline < 0 else newline
            piece = memoryview(chunk)[start:end]
            if self._skipping:
                self._skipped_bytes += len(piece)
            else:
                self._decoder.feed(piece)
                self.peak_retained_bytes = max(
                    self.peak_retained_bytes,
                    self._decoder.peak_retained_bytes,
                )
            if newline < 0:
                return
            if self._skipping:
                self.consumed += self._skipped_bytes + 1
                self._skipped_bytes = 0
                self._skipping = False
                self.oversized = True
                if self._on_unrecoverable is not None:
                    self._on_unrecoverable()
            else:
                self._finish_record(terminated=True)
            start = newline + 1

    def finish(self) -> None:
        """Deliver a final record that never got its newline."""
        if not self._skipping and self._decoder.record_bytes:
            self._finish_record(terminated=False)

    def _finish_record(self, *, terminated: bool) -> None:
        decoder = self._decoder
        row = decoder.finish()
        self.records_decoded += decoder.full_decodes
        self.oversized = self.oversized or decoder.unrecoverable
        if decoder.unrecoverable and self._on_unrecoverable is not None:
            self._on_unrecoverable()
        if row is not None:
            self._consume(row)
        if terminated:
            self.consumed += decoder.record_bytes + 1
        self._decoder = self._new_decoder()


def decode_record(
    record: bytes,
    *,
    record_limit: int,
    record_factory: Optional[Callable[[int], Any]] = None,
) -> Optional[dict]:
    """Decode one already-delimited record under the same bounds."""
    decoder = (
        record_factory(record_limit)
        if record_factory is not None
        else BufferedJsonRecord(record_limit)
    )
    decoder.feed(record)
    return decoder.finish()


__all__ = [
    "BufferedJsonRecord",
    "RecordStream",
    "decode_record",
    "parse_row",
]
