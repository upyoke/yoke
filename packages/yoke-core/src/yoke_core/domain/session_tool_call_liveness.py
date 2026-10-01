"""Session-state evidence required before an open call can excuse silence.

The server cannot inspect a pid on a worker's machine. Its relay owns process
and native-turn observations; a hook owns running posture. An unfinished call
row alone is never evidence that the turn still runs. Unknown state alarms
normally, and even a clean native exit leaves no running call behind it.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_reclaim_progress import open_tool_call_is_live


def session_call_is_live(record: Mapping[str, Any], *, started_at: str) -> bool:
    """Require a running session, current call, and no observed process death."""
    return (
        record.get("turn_posture") == "running"
        and not record.get("ended_at")
        and not record.get("terminated_at")
        and open_tool_call_is_live(started_at, record.get("last_tool_call_at"))
        and current_native_process_observation(record, include_expected_exit=True)
        is None
    )
