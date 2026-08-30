"""Overdue background waiter arms for the steering fleet report."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from yoke_core.domain.session_background_waiter import (
    background_waiter_columns_present,
)
from yoke_core.domain.steering_fleet_report_detectors import (
    age_seconds,
    marker,
    parse_stamp,
)


@dataclass(frozen=True)
class OverdueBackgroundWaiter:
    """One live claim holder whose wrapper missed its expected heartbeat."""

    session_id: str
    item_id: int
    public_ref: str
    waiter_id: str
    kind: str
    watched_fact: str
    armed_at: str
    expected_by: str
    armed_seconds: int
    overdue_seconds: int


def overdue_background_waiters(
    conn: Any,
    *,
    holders: Sequence[Any],
    now: str,
) -> tuple[OverdueBackgroundWaiter, ...]:
    """Return active arms whose heartbeat deadline passed without completion."""
    by_session = {str(holder.session_id): holder for holder in holders}
    if not by_session or not background_waiter_columns_present(conn):
        return ()
    placeholder = marker(conn)
    holes = ", ".join(placeholder for _ in by_session)
    rows = conn.execute(
        "SELECT session_id, background_waiter_id, background_waiter_kind, "
        "background_waiter_fact, background_waiter_armed_at, "
        "background_waiter_expected_by, background_waiter_completed_at "
        f"FROM harness_sessions WHERE session_id IN ({holes})",
        tuple(by_session),
    ).fetchall()
    current = parse_stamp(now)
    overdue = []
    for raw in rows:
        row = dict(raw)
        expected_by = str(row.get("background_waiter_expected_by") or "")
        if (
            not row.get("background_waiter_id")
            or row.get("background_waiter_completed_at")
            or not expected_by
            or parse_stamp(expected_by) > current
        ):
            continue
        session_id = str(row["session_id"])
        holder = by_session[session_id]
        armed_at = str(row.get("background_waiter_armed_at") or "")
        overdue.append(
            OverdueBackgroundWaiter(
                session_id=session_id,
                item_id=int(holder.item_id),
                public_ref=str(holder.public_ref),
                waiter_id=str(row["background_waiter_id"]),
                kind=str(row.get("background_waiter_kind") or "command"),
                watched_fact=str(
                    row.get("background_waiter_fact") or "watcher completion"
                ),
                armed_at=armed_at,
                expected_by=expected_by,
                armed_seconds=age_seconds(armed_at, now) or 0,
                overdue_seconds=age_seconds(expected_by, now) or 0,
            )
        )
    return tuple(
        sorted(overdue, key=lambda entry: (-entry.overdue_seconds, entry.session_id))
    )


__all__ = ["OverdueBackgroundWaiter", "overdue_background_waiters"]
