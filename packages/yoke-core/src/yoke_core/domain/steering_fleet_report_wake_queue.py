"""Read-only receipt positions while a machine demonstrably drains wake work.

The SQL eligibility matches wake_work_pending and the wake claim's ordering.
It deliberately cannot run the mutating eligibility sweep. Connected relays
and a recent wake_relay attempt bound that permissive view: a sweep that keeps
skipping a receipt must become a finding again when attempts stop.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_relay_policy import relay_policy
from yoke_core.domain.steering_fleet_report_detectors import marker


def draining_wake_positions(
    conn: Any, *, machine_ids: Iterable[str], now: datetime
) -> dict[tuple[str, str], int]:
    """Position each eligible receipt in its actively draining machine queue.

    Count the machine's whole queue, across projects, before report visibility
    filters select which receipts may be shown. No private receipt ids escape.
    """
    machines = tuple(sorted({value for value in machine_ids if value}))
    if not machines:
        return {}
    p = marker(conn)
    current = instant_parameter(conn, now)
    recent = instant_parameter(
        conn, now - timedelta(seconds=3 * relay_policy().poll_seconds)
    )
    rows = conn.execute(
        "SELECT r.message_id,r.session_id,"
        "ROW_NUMBER() OVER (PARTITION BY r.machine_id "
        "ORDER BY r.wake_after,r.message_id,r.session_id) AS queue_position "
        "FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"WHERE r.machine_id IN ({','.join(p for _ in machines)}) "
        "AND r.state='pending' AND m.cancelled_at IS NULL "
        f"AND r.wake_after<={p} AND m.expires_at>{p} "
        "AND (r.injection_lease_id IS NULL OR ("
        "r.injection_lease_expires_at IS NOT NULL "
        f"AND r.injection_lease_expires_at<={p})) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=r.message_id AND a.target_session_id=r.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL) "
        "AND EXISTS (SELECT 1 FROM session_relays relay "
        "WHERE relay.machine_id=r.machine_id "
        f"AND relay.connected_until>={p} AND relay.state IN ('active','idle')) "
        "AND EXISTS (SELECT 1 FROM session_message_attempts progress "
        "JOIN session_message_recipients receipt "
        "ON receipt.message_id=progress.message_id "
        "AND receipt.session_id=progress.target_session_id "
        "WHERE receipt.machine_id=r.machine_id "
        "AND progress.attempt_kind='wake_relay' "
        f"AND progress.started_at>={p} AND progress.started_at<={p})",
        (*machines, current, current, current, current, recent, current),
    ).fetchall()
    return {
        (str(row["message_id"]), str(row["session_id"])): int(row["queue_position"])
        for row in rows
    }
