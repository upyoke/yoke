"""Decode ordinary harness records whole; project the huge ones.

A record small enough to hold is parsed in C, exactly as a general reader
parses it, because that is both faster and stricter than anything written
here. A record past that bound is walked as a byte stream instead, and
only the scalars its reader declared survive the walk — so a fourteen
megabyte compacted turn costs the memory of the handful of fields the
reader came for.

What separates this from a size limit is that it also answers whether the
loss mattered. ``RecordProjection.incomplete`` inspects the projected
record and says whether this reader needed a fact the projection did not
carry. A giant record of content nobody reads is then not a gap at all,
while a giant record whose usage statement could not be read still is —
which is the difference between an honest reading and a reading marked
partial because something irrelevant happened to be large.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from yoke_harness.artifact_record_stream import parse_row
from yoke_harness.json_stream_walker import JsonStreamWalker


@dataclass(frozen=True)
class RecordProjection:
    """Which scalars a projected record keeps, and when it lost one."""

    #: Paths, as key tuples from the record root, whose scalars are kept.
    #: ``"*"`` stands for any array member.
    selected_paths: frozenset[tuple[str, ...]]
    #: Given a fully projected record, whether this reader needed a fact
    #: the projection did not carry. Consulted only for oversized records.
    incomplete: Callable[[dict[str, Any]], bool]


class ProjectingRecordDecoder:
    """Decode ordinary rows in C; project only rows beyond the normal bound."""

    def __init__(self, record_limit: int, projection: RecordProjection) -> None:
        self._record_limit = record_limit
        self._projection = projection
        self._buffer = bytearray()
        self._projecting = False
        self._row: dict[str, Any] = {}
        self._walker = JsonStreamWalker(
            select=lambda path: path in projection.selected_paths,
            emit=self._keep,
        )
        self.record_bytes = 0
        self.peak_retained_bytes = 0
        self.unrecoverable = False
        self.full_decodes = 0

    def feed(self, data: bytes | memoryview) -> None:
        self.record_bytes += len(data)
        if not self._projecting:
            room = self._record_limit + 1 - len(self._buffer)
            self._buffer.extend(data[:room])
            self.peak_retained_bytes = max(self.peak_retained_bytes, len(self._buffer))
            if len(self._buffer) <= self._record_limit:
                return
            prefix = bytes(self._buffer)
            self._buffer.clear()
            self._projecting = True
            self._walk(prefix)
            data = data[room:]
        if self._walker.invalid:
            return
        self._walk(bytes(data))

    def finish(self) -> Optional[dict[str, Any]]:
        if not self._projecting:
            self.full_decodes = 1
            return parse_row(bytes(self._buffer))
        self._walker.finish()
        complete = self._walker.complete
        self.unrecoverable = self.record_bytes > self._record_limit and (
            not complete
            or self._walker.overflowed
            or self._projection.incomplete(self._row)
        )
        return self._row if complete else None

    def _walk(self, data: bytes) -> None:
        self._walker.feed(data)
        self.peak_retained_bytes = max(
            self.peak_retained_bytes, self._walker.peak_retained_bytes
        )

    def _keep(self, path: tuple[str, ...], value: Any) -> None:
        target = self._row
        for key in path[:-1]:
            child = target.get(key)
            if not isinstance(child, dict):
                child = {}
                target[key] = child
            target = child
        target[path[-1]] = value


def projection_decoder(
    projection: RecordProjection,
) -> Callable[[int], ProjectingRecordDecoder]:
    """Return the record factory a scan uses to read with ``projection``."""

    def decoder(record_limit: int) -> ProjectingRecordDecoder:
        return ProjectingRecordDecoder(record_limit, projection)

    return decoder


__all__ = [
    "ProjectingRecordDecoder",
    "RecordProjection",
    "projection_decoder",
]
