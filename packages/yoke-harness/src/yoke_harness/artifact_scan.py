"""Stream growing JSONL artifacts under record, scan, and tail bounds.

Whole-record decoding remains bounded for general callers. Callers that
provide a record factory may instead project small facts while bytes stream.
Every loss or unfinished scan is surfaced on :class:`ScanResult`.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

#: The longest single record a general reader parses as one JSON object.
MAX_RECORD_BYTES = 1 << 20

#: The most bytes one invocation reads; arrears fold over later events.
MAX_SCAN_BYTES = 8 << 20

MAX_TAIL_BYTES = 1 << 20
_READ_CHUNK_BYTES = 1 << 16

OVERSIZED_RECORD_REASON = (
    "a record in the harness artifact exceeded the reader's record bound "
    "and was skipped, so anything it stated is not counted"
)

CATCH_UP_PENDING_REASON = (
    "the harness artifact holds more unread content than one read folds, "
    "so this reading stops short of its end and the next read resumes there"
)


@dataclass(frozen=True)
class ScanResult:
    """Where a scan finished, and what it could not account for."""

    offset: int
    oversized: bool = False
    caught_up: bool = True
    bytes_read: int = 0
    records_decoded: int = 0
    peak_retained_bytes: int = 0


def parse_row(record: bytes) -> Optional[dict]:
    """Return one JSON object, or ``None`` for anything else."""
    if not record.strip():
        return None
    try:
        parsed = json.loads(record)
    except (json.JSONDecodeError, TypeError, ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def scan_rows(
    artifact: Path,
    offset: int,
    consume: Callable[[dict], Any],
    *,
    max_scan_bytes: Optional[int] = None,
    record_factory: Optional[Callable[[int], Any]] = None,
    on_unrecoverable: Optional[Callable[[], Any]] = None,
) -> ScanResult:
    """Fold the complete records after ``offset``, one at a time.

    The offset advances over complete records or fragments explicitly marked
    unrecoverable. A trailing partial record remains for the next read, so a
    harness appending during the scan is never believed halfway through.
    """
    max_scan_bytes = MAX_SCAN_BYTES if max_scan_bytes is None else max_scan_bytes
    read = 0
    caught_up = True
    try:
        with artifact.open("rb") as handle:
            starts_inside_record = False
            if offset > 0:
                handle.seek(offset - 1)
                starts_inside_record = handle.read(1) != b"\n"
            handle.seek(offset)
            drain = _Drain(
                consume,
                record_factory=record_factory,
                skip_record=starts_inside_record,
                on_unrecoverable=on_unrecoverable,
            )
            while read < max_scan_bytes:
                chunk = handle.read(min(_READ_CHUNK_BYTES, max_scan_bytes - read))
                if not chunk:
                    break
                read += len(chunk)
                drain.feed(chunk)
            else:
                caught_up = not handle.read(1)
    except OSError:
        return ScanResult(offset=offset)
    abandon_current = drain.current_unrecoverable and read > drain.consumed
    if read > 0 and (abandon_current or (drain.consumed == 0 and not caught_up)):
        if on_unrecoverable is not None:
            on_unrecoverable()
        return ScanResult(
            offset=offset + read,
            oversized=True,
            caught_up=False,
            bytes_read=read,
            records_decoded=drain.records_decoded,
            peak_retained_bytes=drain.peak_retained_bytes,
        )
    return ScanResult(
        offset=offset + drain.consumed,
        oversized=drain.oversized or drain.current_unrecoverable,
        caught_up=caught_up,
        bytes_read=read,
        records_decoded=drain.records_decoded,
        peak_retained_bytes=drain.peak_retained_bytes,
    )


def iter_rows(
    artifact: Path,
    *,
    max_bytes: Optional[int] = None,
    record_factory: Optional[Callable[[int], Any]] = None,
) -> Iterator[dict]:
    """Yield records from the start under the same bounds as a scan.

    For a reader that stops as soon as it has what it came for — session
    metadata is stated once, near the beginning — so the rest of the file
    is never read at all. Unlike a resumable fold, this reader delivers a
    final record that has no trailing newline: it advances no offset, so
    nothing is lost by reading a record that may still be growing, and a
    harness that writes its metadata without a trailing newline would
    otherwise state its identity to nobody.
    """
    max_bytes = MAX_SCAN_BYTES if max_bytes is None else max_bytes
    pending: deque[dict] = deque()
    drain = _Drain(pending.append, record_factory=record_factory)
    read = 0
    try:
        handle = artifact.open("rb")
    except OSError:
        return
    with handle:
        while read < max_bytes:
            try:
                chunk = handle.read(min(_READ_CHUNK_BYTES, max_bytes - read))
            except OSError:
                return
            if not chunk:
                break
            read += len(chunk)
            drain.feed(chunk)
            while pending:
                yield pending.popleft()
        else:
            return
        drain.finish()
        while pending:
            yield pending.popleft()


def tail_rows_newest_first(
    artifact: Path,
    *,
    max_rows: Optional[int] = None,
    max_bytes: Optional[int] = None,
    record_factory: Optional[Callable[[int], Any]] = None,
) -> Iterator[dict]:
    """Yield the newest complete records, newest first.

    Only the last ``max_bytes`` are read, and the record the window cut in
    half is skipped by moving the floor past it rather than by copying the
    remainder, so the window exists once. A reader that wants the latest
    turn therefore pays for its window, not for the session. Records are
    parsed as they are yielded, so a reader that stops at the first match
    — which is what "newest wins" means — never materializes the rest.

    A final record with no trailing newline is read like any other: this
    reader advances no offset, so it loses nothing by looking, and a
    half-written record is not valid JSON and is dropped rather than
    half-believed. Requiring the newline instead would blind the reader
    to a whole artifact that has only ever been written once.
    """
    max_bytes = MAX_TAIL_BYTES if max_bytes is None else max_bytes
    start = 0
    try:
        with artifact.open("rb") as handle:
            handle.seek(0, 2)
            start = max(0, handle.tell() - max_bytes)
            handle.seek(start)
            window = handle.read(max_bytes)
    except OSError:
        return
    floor = 0
    if start > 0:
        cut = window.find(b"\n")
        if cut < 0:
            return
        floor = cut + 1
    end = len(window)
    yielded = 0
    while end > floor:
        if max_rows is not None and yielded >= max_rows:
            return
        cut = window.rfind(b"\n", floor, end)
        record = window[cut + 1 : end] if cut >= floor else window[floor:end]
        end = cut if cut >= floor else floor
        row = _decode_record(record, record_factory)
        if row is not None:
            yielded += 1
            yield row


class _BufferedJsonRecord:
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


class _Drain:
    """Split a byte stream while each decoder retains only bounded state."""

    def __init__(
        self,
        consume: Callable[[dict], Any],
        *,
        record_factory: Optional[Callable[[int], Any]] = None,
        skip_record: bool = False,
        on_unrecoverable: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._consume = consume
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
    def current_unrecoverable(self) -> bool:
        return bool(self._decoder.unrecoverable) if not self._skipping else True

    def _new_decoder(self) -> Any:
        if self._record_factory is not None:
            return self._record_factory(MAX_RECORD_BYTES)
        return _BufferedJsonRecord(MAX_RECORD_BYTES)

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


def _decode_record(
    record: bytes, record_factory: Optional[Callable[[int], Any]]
) -> Optional[dict]:
    decoder = (
        record_factory(MAX_RECORD_BYTES)
        if record_factory is not None
        else _BufferedJsonRecord(MAX_RECORD_BYTES)
    )
    decoder.feed(record)
    return decoder.finish()


__all__ = [
    "CATCH_UP_PENDING_REASON",
    "MAX_RECORD_BYTES",
    "MAX_SCAN_BYTES",
    "MAX_TAIL_BYTES",
    "OVERSIZED_RECORD_REASON",
    "ScanResult",
    "iter_rows",
    "parse_row",
    "scan_rows",
    "tail_rows_newest_first",
]
