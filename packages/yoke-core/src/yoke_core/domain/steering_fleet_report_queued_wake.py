"""When a queued explicit wake may be released, as the report reads it.

An explicit wake the delivery plane never attempted blocks every later wake
request for its session. The wake command releases such a receipt, but only
once it has waited out the wake acknowledgement grace counted from its own
creation; inside that window it refuses the request as in flight. The report
offers the release only when the command would take it, so it computes the
same moment here from the same policy grace.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from yoke_core.domain.session_explicit_wake import explicit_stopped_wake_requested
from yoke_core.domain.session_message_types import parse_timestamp


def unattempted_explicit_wake(record: Mapping[str, Any]) -> bool:
    """True for an explicit wake receipt the plane has made no attempt on."""
    return int(record.get("wake_attempt_count") or 0) == 0 and (
        explicit_stopped_wake_requested(record.get("routing_snapshot"))
    )


def wake_release_times(
    records: Iterable[Mapping[str, Any]], *, grace: timedelta
) -> dict[str, datetime]:
    """When each session's unattempted explicit wakes all become releasable.

    The wake command releases only receipts that have waited out the grace
    and refuses while any younger one remains, so the session's newest
    queued wake decides, whichever delivery state that receipt is in.
    """
    release_at: dict[str, datetime] = {}
    for record in records:
        created = parse_timestamp(record.get("created_at"))
        if created is None or not unattempted_explicit_wake(record):
            continue
        session_id = str(record["session_id"])
        moment = created + grace
        release_at[session_id] = max(moment, release_at.get(session_id, moment))
    return release_at


__all__ = ["unattempted_explicit_wake", "wake_release_times"]
