"""Keep operator-driven mail on its hook route and name the pending action."""

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_core.domain.session_operator_wake_notice import notify_operator_to_wake
from yoke_core.domain.session_message_wake_skip import record_wake_skip
from yoke_core.domain.session_message_starvation import turn_in_flight


def keep_operator_hook_route(
    conn: Any,
    row: Mapping[str, Any],
    *,
    now: datetime,
    grace_seconds: int,
    liveness: str,
) -> bool:
    if native_wake_supported(row.get("executor_surface"), row.get("launch_origin")):
        return False
    notify_operator_to_wake(conn, row, now=now, grace_seconds=grace_seconds)
    if turn_in_flight(row, now=now) is None:
        record_wake_skip(
            conn,
            row,
            operation="message_stopped",
            relay_versions={},
            liveness=liveness,
            now=now,
        )
    return True
