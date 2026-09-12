"""Stream growing JSONL artifacts under record, scan, and tail bounds.

Whole-record decoding remains bounded for general callers. Callers that
provide a record factory may instead project small facts while bytes stream.
Every loss or unfinished scan is surfaced on :class:`ScanResult`.

The scan budget bounds how much one invocation *starts*, not where it may
stop. A scan that reaches its budget in the middle of a record keeps
reading to that record's end, because stopping there would leave the
offset inside a record no later read can enter: the next read skips
forward to the following newline and everything the record stated is gone.
A harness that writes one compacted record larger than the whole budget is
the case that made this real, and it is exactly the record a reader most
wants. Finishing is itself bounded by
:data:`MAX_RECORD_COMPLETION_BYTES`, so a record with no end in sight —
corrupt, or still growing without a newline — is abandoned deliberately
and said out loud rather than read forever.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from yoke_harness.artifact_record_stream import (
    RecordStream,
    decode_record,
    parse_row,
)

#: The longest single record a general reader parses as one JSON object.
MAX_RECORD_BYTES = 1 << 20

#: The most bytes one invocation starts reading; arrears fold over later
#: events.
MAX_SCAN_BYTES = 8 << 20

#: How far past that budget one invocation keeps reading to finish the
#: record it is already inside, rather than abandon it mid-record.
MAX_RECORD_COMPLETION_BYTES = 32 << 20

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


def scan_rows(
    artifact: Path,
    offset: int,
    consume: Callable[[dict], Any],
    *,
    max_scan_bytes: Optional[int] = None,
    max_record_completion_bytes: Optional[int] = None,
    record_factory: Optional[Callable[[int], Any]] = None,
    on_unrecoverable: Optional[Callable[[], Any]] = None,
) -> ScanResult:
    """Fold the complete records after ``offset``, one at a time.

    The offset advances over complete records or fragments explicitly marked
    unrecoverable. A trailing partial record remains for the next read, so a
    harness appending during the scan is never believed halfway through.
    """
    max_scan_bytes = MAX_SCAN_BYTES if max_scan_bytes is None else max_scan_bytes
    completion = (
        MAX_RECORD_COMPLETION_BYTES
        if max_record_completion_bytes is None
        else max_record_completion_bytes
    )
    read = 0
    caught_up = True
    try:
        with artifact.open("rb") as handle:
            starts_inside_record = False
            if offset > 0:
                handle.seek(offset - 1)
                starts_inside_record = handle.read(1) != b"\n"
            handle.seek(offset)
            stream = RecordStream(
                consume,
                record_limit=MAX_RECORD_BYTES,
                record_factory=record_factory,
                skip_record=starts_inside_record,
                on_unrecoverable=on_unrecoverable,
            )
            limit = max_scan_bytes
            finishing = False
            while True:
                if read >= limit:
                    if stream.inside_record and not finishing and completion > 0:
                        limit = max_scan_bytes + completion
                        finishing = True
                        continue
                    caught_up = not handle.read(1)
                    break
                chunk = handle.read(min(_READ_CHUNK_BYTES, limit - read))
                if not chunk:
                    break
                if finishing:
                    newline = chunk.find(b"\n")
                    if newline >= 0:
                        # Ending the record the budget landed inside is
                        # the only reason to read past that budget, so
                        # the scan stops on its newline. Whatever else
                        # this read happened to hold is left unfed and
                        # read again next time, which keeps the budget a
                        # bound rather than a suggestion.
                        chunk = chunk[: newline + 1]
                        read += len(chunk)
                        stream.feed(chunk)
                        handle.seek(offset + stream.consumed)
                        caught_up = not handle.read(1)
                        break
                read += len(chunk)
                stream.feed(chunk)
    except OSError:
        return ScanResult(offset=offset)
    abandoned = stream.current_unrecoverable and read > stream.consumed
    starved = stream.inside_record and stream.consumed == 0 and not caught_up
    if read > 0 and (abandoned or starved):
        if on_unrecoverable is not None:
            on_unrecoverable()
        return ScanResult(
            offset=offset + read,
            oversized=True,
            caught_up=False,
            bytes_read=read,
            records_decoded=stream.records_decoded,
            peak_retained_bytes=stream.peak_retained_bytes,
        )
    return ScanResult(
        offset=offset + stream.consumed,
        oversized=stream.oversized,
        caught_up=caught_up,
        bytes_read=read,
        records_decoded=stream.records_decoded,
        peak_retained_bytes=stream.peak_retained_bytes,
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
    stream = RecordStream(
        pending.append,
        record_limit=MAX_RECORD_BYTES,
        record_factory=record_factory,
    )
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
            stream.feed(chunk)
            while pending:
                yield pending.popleft()
        else:
            return
        stream.finish()
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

    A window that falls entirely inside one enormous record yields
    nothing, which is deliberate: this reader answers "what is the newest
    statement" for facts every turn restates, so the next event's read
    answers it once an ordinary record follows. A fact that must survive
    such a record is folded incrementally with :func:`scan_rows` instead.
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
        row = decode_record(
            record, record_limit=MAX_RECORD_BYTES, record_factory=record_factory
        )
        if row is not None:
            yielded += 1
            yield row


__all__ = [
    "CATCH_UP_PENDING_REASON",
    "MAX_RECORD_BYTES",
    "MAX_RECORD_COMPLETION_BYTES",
    "MAX_SCAN_BYTES",
    "MAX_TAIL_BYTES",
    "OVERSIZED_RECORD_REASON",
    "ScanResult",
    "iter_rows",
    "parse_row",
    "scan_rows",
    "tail_rows_newest_first",
]
