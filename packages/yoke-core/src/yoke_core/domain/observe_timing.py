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
    "measure_elapsed",
    "parse_captured_timestamp",
]
