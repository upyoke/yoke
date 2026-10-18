"""Session-state evidence required before an open call can excuse silence.

The server cannot inspect a pid on a worker's machine. Its relay owns process
and native-turn observations; a hook owns running posture. An unfinished call
row alone is never evidence that the turn still runs. Unknown state alarms
normally, and even a clean native exit leaves no running call behind it.
Parking ends the turn, so a call that started before the park is not live
either.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.session_queue_posture import SESSION_MODE_PARKED
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_reclaim_progress import open_tool_call_is_live


def open_call_predates_park(
    record: Mapping[str, Any], *, started_at: datetime | str | None
) -> bool:
    """True when the session parked after this open call started.

    A parked write advances ``turn_posture_at``, and any later accepted
    prompt clears the park, so an older open call is one whose completion
    hook never recorded. A call opened after the park is still live.
    """
    if str(record.get("mode") or "") != SESSION_MODE_PARKED:
        return False
    since = parse_timestamp(started_at)
    parked_at = parse_timestamp(record.get("turn_posture_at"))
    return since is not None and parked_at is not None and since < parked_at


def session_call_is_live(
    record: Mapping[str, Any], *, started_at: datetime | str | None
) -> bool:
    """Require a running session, current call, and no observed process death."""
    return (
        record.get("turn_posture") == "running"
        and not record.get("ended_at")
        and not record.get("terminated_at")
        and open_tool_call_is_live(started_at, record.get("last_tool_call_at"))
        and not open_call_predates_park(record, started_at=started_at)
        and current_native_process_observation(record, include_expected_exit=True)
        is None
    )
