"""When the direct native route hands this receipt to the peer-hook broker.

A direct wake that ended badly should not immediately claim itself again:
the broker is the other route, and letting the direct route retry in a tight
loop is how a receipt burns its whole wake budget on one failing path. So a
failed direct outcome parks the direct route for as long as a broker job may
take, and the broker gets first refusal.

One outcome earns a second direct try before that hand-off. A resume that
produced a turn and no injection used to prove the direct route could not
reach the session, because delivery depended on the resumed turn making some
tool call of its own and a turn that answers in prose makes none. The wake
instruction no longer depends on that: it names the command that returns the
message body as the turn's first action, so the read happens inside a tool
call the instruction asked for. A single undelivered turn is now evidence
that one turn ignored its instruction, not that the route is closed — and
the cheapest way to tell those apart is to ask once more. A second one is
the route, and hands off.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from yoke_contracts.session_control.wake_delivery import (
    TURN_WITHOUT_INJECTION_RESULT,
)
from yoke_core.domain.session_message_types import parse_timestamp, utc_now
from yoke_core.domain.session_relay_storage import marker


#: How long a failed direct wake leaves the route to the broker. It is the
#: broker job's own timeout: any less and the direct route reclaims a
#: receipt the broker is still working.
BROKER_JOB_TIMEOUT_SECONDS = 300

#: Direct outcomes that hand the receipt to the peer-hook broker.
DIRECT_FALLBACK_RESULTS = frozenset(
    {
        "failed",
        # A native resume that delivered nothing has proved the direct route
        # cannot reach this turn -- once the retry below has been spent.
        TURN_WITHOUT_INJECTION_RESULT,
        "not_found",
        "outcome_unknown",
        "relay_lease_expired",
        "unsupported_surface",
        "version_mismatch",
    }
)

#: Undelivered direct turns allowed before the broker takes the receipt.
DIRECT_UNDELIVERED_TURN_RETRIES = 1


def _latest_wake_result(
    conn: Any, *, message_id: str, session_id: str
) -> tuple[str, str, str] | None:
    p = marker(conn)
    row = conn.execute(
        "SELECT attempt_kind,result_code,completed_at FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        "AND attempt_kind IN ('wake_relay','wake_broker') "
        "AND completed_at IS NOT NULL ORDER BY started_at DESC,attempt_id DESC LIMIT 1",
        (message_id, session_id),
    ).fetchone()
    return (
        (str(row[0]), str(row[1] or ""), str(row[2] or "")) if row is not None else None
    )


def _undelivered_direct_turns(conn: Any, *, message_id: str, session_id: str) -> int:
    p = marker(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        f"AND attempt_kind='wake_relay' AND result_code={p}",
        (message_id, session_id, TURN_WITHOUT_INJECTION_RESULT),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def direct_wake_waits_for_broker(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: datetime | str | None = None,
) -> bool:
    """Keep a failed direct route from immediately claiming itself again."""
    latest = _latest_wake_result(conn, message_id=message_id, session_id=session_id)
    if not latest or latest[0] != "wake_relay":
        return False
    kind, result_code, completed_at = latest
    if result_code not in DIRECT_FALLBACK_RESULTS:
        return False
    completed = parse_timestamp(completed_at)
    current = parse_timestamp(now) if isinstance(now, str) else now
    if not completed or (current or utc_now()) >= completed + timedelta(
        seconds=BROKER_JOB_TIMEOUT_SECONDS
    ):
        return False
    if result_code == TURN_WITHOUT_INJECTION_RESULT:
        return (
            _undelivered_direct_turns(
                conn, message_id=message_id, session_id=session_id
            )
            > DIRECT_UNDELIVERED_TURN_RETRIES
        )
    return True


__all__ = [
    "BROKER_JOB_TIMEOUT_SECONDS",
    "DIRECT_FALLBACK_RESULTS",
    "DIRECT_UNDELIVERED_TURN_RETRIES",
    "direct_wake_waits_for_broker",
]
