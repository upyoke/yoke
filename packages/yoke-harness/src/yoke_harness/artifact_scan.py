"""Read a growing harness transcript without ever holding one in memory.

A harness transcript is append-only newline-delimited JSON, and it grows
for as long as its session runs — one observed Codex rollout reached 1.9
GB. Every reader here therefore streams: bytes arrive in fixed chunks,
each complete record is parsed and handed to the caller, and nothing but
the caller's own accumulator survives the record it came from. A reader
that instead read the unread tail whole, kept its lines, and kept the
objects it parsed from them held several multiples of the file at once —
Python stores a mostly-ASCII string containing one emoji four bytes per
character, so a 1 MiB record measured an 8 MiB peak.

Two bounds keep one invocation's cost stated rather than discovered.
:data:`MAX_RECORD_BYTES` caps a single record, because a record larger
than that is a source defect and parsing it is the allocation this module
exists to prevent. :data:`MAX_SCAN_BYTES` caps the whole invocation, so an
artifact that grew faster than the reads folding it is caught up over
several events instead of one enormous one.

Neither bound is allowed to be silent. A skipped oversized record and an
invocation that stopped short of the end are both reported on the
:class:`ScanResult`, so the caller can say its reading is partial rather
than presenting an understated total as complete.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional


#: The longest single record any reader here parses. One transcript row is
#: one turn's JSON; anything larger is a defect in the source, and the
#: point of a bound is that meeting one costs no more than skipping it.
MAX_RECORD_BYTES = 1 << 20

#: The most bytes one invocation reads. A hook event is a poor place to
#: fold a gigabyte, so a large arrears is folded across several of them.
MAX_SCAN_BYTES = 8 << 20

#: The window read back from the end when only the newest records matter.
MAX_TAIL_BYTES = 1 << 20

_READ_CHUNK_BYTES = 1 << 16

#: Recorded when a record exceeded :data:`MAX_RECORD_BYTES` and was skipped.
OVERSIZED_RECORD_REASON = (
    "a record in the harness artifact exceeded the reader's record bound "
    "and was skipped, so anything it stated is not counted"
)

#: Recorded when an invocation stopped at :data:`MAX_SCAN_BYTES`.
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
) -> ScanResult:
    """Fold the complete records after ``offset``, one at a time.

    The returned offset advances only over records that were handed to
    ``consume``, so a fold that crashes re-reads rather than skips. A
    trailing partial record is left unread: a harness appending while this
    runs would otherwise have its record parsed as truncated JSON and
    dropped, and the next read picks it up whole.
    """
    max_scan_bytes = MAX_SCAN_BYTES if max_scan_bytes is None else max_scan_bytes
    drain = _Drain(consume)
    read = 0
    caught_up = True
    try:
        with artifact.open("rb") as handle:
            handle.seek(offset)
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
    return ScanResult(
        offset=offset + drain.consumed,
        oversized=drain.oversized,
        caught_up=caught_up,
    )


def iter_rows(
    artifact: Path, *, max_bytes: Optional[int] = None
) -> Iterator[dict]:
    """Yield records from the start under the same bounds as a scan.

    For a reader that stops as soon as it has what it came for — session
    metadata is stated once, near the beginning — so the rest of the file
    is never read at all.
    """
    max_bytes = MAX_SCAN_BYTES if max_bytes is None else max_bytes
    pending: deque[dict] = deque()
    drain = _Drain(pending.append)
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


def tail_rows_newest_first(
    artifact: Path,
    *,
    max_rows: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> Iterator[dict]:
    """Yield the newest complete records, newest first.

    Only the last ``max_bytes`` are read, and the record the window cut in
    half is skipped by moving the floor past it rather than by copying the
    remainder, so the window exists once. A reader that wants the latest
    turn therefore pays for its window, not for the session. Records are
    parsed as they are yielded, so a reader that stops at the first match
    — which is what "newest wins" means — never materializes the rest.
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
        if len(record) > MAX_RECORD_BYTES:
            continue
        row = parse_row(record)
        if row is not None:
            yielded += 1
            yield row


class _Drain:
    """Turn a byte stream into records, holding at most one at a time."""

    def __init__(self, consume: Callable[[dict], Any]) -> None:
        self._consume = consume
        self._buffer = bytearray()
        self._skipping = False
        self.consumed = 0
        self.oversized = False

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        while True:
            index = self._buffer.find(b"\n")
            if index < 0:
                break
            record = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            self.consumed += index + 1
            if self._skipping:
                self._skipping = False
                continue
            self._deliver(record)
        if len(self._buffer) > MAX_RECORD_BYTES:
            self.consumed += len(self._buffer)
            self._buffer.clear()
            self._skipping = True
            self.oversized = True

    def _deliver(self, record: bytes) -> None:
        if len(record) > MAX_RECORD_BYTES:
            self.oversized = True
            return
        row = parse_row(record)
        if row is not None:
            self._consume(row)


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
