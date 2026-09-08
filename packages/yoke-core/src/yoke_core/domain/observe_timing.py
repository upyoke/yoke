"""Elapsed time between the timestamps a hook captured at the tool boundary.

A tool call's duration is the interval between two *captured* endpoints —
the instant the PreToolUse hook observed the call opening and the instant
the PostToolUse hook observed it closing. It is never the interval between
a captured start and the moment telemetry happened to reach the database.

Read-only hook evaluations are answered from warm local state and their
observations are delivered afterwards in bounded batches, so ingest time
trails the tool's completion by however long delivery took. Measuring
against ingest time charges that delivery delay to the tool: matched Read
calls recorded 4079ms against a real 1649ms, and Grep 6090ms against 3979ms.
So callers pass both endpoints, the delivery delay is reported beside the
duration as its own measurement, and an endpoint that is missing or
impossible is named rather than quietly dropped.

Delivery can also reorder the two observations, so this module owns which
of two captured starts a call actually began at, and whether a stored start
was captured at all or synthesized by a completion that arrived first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Union

CapturedTimestamp = Union[str, datetime, None]

# A tool call can legitimately run for a long time — a background watcher, a
# CI-routed verification gate, a long build. The ceiling exists to catch two
# endpoints that do not belong to the same call (a stale row, a misjoined
# lookup), not to cap how slow a real tool is allowed to be.
MAX_PLAUSIBLE_ELAPSED_MS = 24 * 60 * 60 * 1000

TIMING_MEASURED = "measured"
TIMING_UNKNOWN_NO_CALL_IDENTITY = "unknown_no_call_identity"
TIMING_UNKNOWN_NO_RECORDED_START = "unknown_no_recorded_start"
TIMING_UNKNOWN_NO_CAPTURED_END = "unknown_no_captured_end"
TIMING_UNKNOWN_LOOKUP_FAILED = "unknown_lookup_failed"
TIMING_INVALID_ENDPOINT_FORMAT = "invalid_endpoint_format"
TIMING_INVALID_NEGATIVE_ELAPSED = "invalid_negative_elapsed"
TIMING_INVALID_IMPLAUSIBLE_ELAPSED = "invalid_implausible_elapsed"


@dataclass(frozen=True)
class ElapsedMeasurement:
    """An elapsed interval, or the named reason there is not one.

    ``milliseconds`` is populated only for :data:`TIMING_MEASURED`. Every
    other status carries ``None`` and says which endpoint was missing or
    what made the pair impossible, so a reader can tell "we did not observe
    this" from "this was fast".
    """

    milliseconds: Optional[int]
    status: str


def parse_captured_timestamp(value: CapturedTimestamp) -> Optional[datetime]:
    """Read one captured endpoint as an aware UTC datetime.

    Endpoints reach this module from several writers — an ISO string on a
    telemetry envelope, a ``session_tool_calls`` column, a live
    ``HookContext.now``. A stored value without an offset is read as UTC,
    matching how every writer stamps it; anything unparseable returns
    ``None`` so the caller can name the format failure.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def measure_elapsed(
    start: CapturedTimestamp,
    end: CapturedTimestamp,
    *,
    missing_start_status: str = TIMING_UNKNOWN_NO_RECORDED_START,
) -> ElapsedMeasurement:
    """Measure ``end - start``, naming why when the pair cannot be measured.

    ``missing_start_status`` lets a caller say what a missing start means in
    its own vocabulary; the classification of the interval itself is shared.
    """
    if start is None or (isinstance(start, str) and not start.strip()):
        return ElapsedMeasurement(None, missing_start_status)
    if end is None or (isinstance(end, str) and not end.strip()):
        return ElapsedMeasurement(None, TIMING_UNKNOWN_NO_CAPTURED_END)
    started = parse_captured_timestamp(start)
    ended = parse_captured_timestamp(end)
    if started is None or ended is None:
        return ElapsedMeasurement(None, TIMING_INVALID_ENDPOINT_FORMAT)
    elapsed_ms = int(round((ended - started).total_seconds() * 1000))
    if elapsed_ms < 0:
        return ElapsedMeasurement(None, TIMING_INVALID_NEGATIVE_ELAPSED)
    if elapsed_ms > MAX_PLAUSIBLE_ELAPSED_MS:
        return ElapsedMeasurement(None, TIMING_INVALID_IMPLAUSIBLE_ELAPSED)
    return ElapsedMeasurement(elapsed_ms, TIMING_MEASURED)


def arriving_start_supersedes(
    stored_start: CapturedTimestamp,
    arriving_start: CapturedTimestamp,
) -> bool:
    """Decide whether a late-arriving captured start replaces the stored one.

    Observations do not always arrive in the order they happened: a
    completion delivered ahead of its own call's opening observation writes
    the row first, so the genuine start meets a row that already exists. The
    earlier of two valid starts is the one the call actually began at, and a
    start that cannot be read as a timestamp is not evidence of anything —
    so a valid arrival replaces an unreadable stored value, and a stored
    value that is already earlier or equal stands.

    Replay is covered by the same rule rather than by a separate one: a
    re-delivered start carries the instant it always carried, which is never
    earlier than the stored copy of itself.
    """
    arriving = parse_captured_timestamp(arriving_start)
    if arriving is None:
        return False
    stored = parse_captured_timestamp(stored_start)
    if stored is None:
        return True
    return arriving < stored


def start_endpoint_is_synthesized(
    started_at: CapturedTimestamp,
    completed_at: CapturedTimestamp,
) -> bool:
    """Report whether a stored start is the completion stamping its own row.

    A completion with no open row to close inserts one already closed and
    writes its own instant into both endpoints, so the call stays counted
    and the row stays coherent. That placeholder is not a captured start:
    measuring against it reports a zero-length call for a call nobody
    observed opening, which reads as "instant" rather than "unobserved".

    The two endpoints hold the same instant only when one write produced
    both — they are otherwise captured by separate hook invocations at
    millisecond resolution — so the placeholder identifies itself and needs
    no column to mark it. Once the genuine start arrives and supersedes it,
    the endpoints differ and the same read measures the real interval.
    """
    start = parse_captured_timestamp(started_at)
    end = parse_captured_timestamp(completed_at)
    if start is None or end is None:
        return False
    return start == end


__all__ = [
    "CapturedTimestamp",
    "ElapsedMeasurement",
    "MAX_PLAUSIBLE_ELAPSED_MS",
    "TIMING_INVALID_ENDPOINT_FORMAT",
    "TIMING_INVALID_IMPLAUSIBLE_ELAPSED",
    "TIMING_INVALID_NEGATIVE_ELAPSED",
    "TIMING_MEASURED",
    "TIMING_UNKNOWN_LOOKUP_FAILED",
    "TIMING_UNKNOWN_NO_CALL_IDENTITY",
    "TIMING_UNKNOWN_NO_CAPTURED_END",
    "TIMING_UNKNOWN_NO_RECORDED_START",
    "arriving_start_supersedes",
    "measure_elapsed",
    "parse_captured_timestamp",
    "start_endpoint_is_synthesized",
]
