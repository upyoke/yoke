"""Deadline convergence for queued and in-flight session launches."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_store import (
    add_seconds,
    begin_mutation,
    list_launches,
    marker,
    parse_time,
    update_launch,
    utc_now,
    value,
)
from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS, LaunchRecord


def settle_launch_deadlines(conn: Any, *, now: str | None = None) -> list[LaunchRecord]:
    """Close expired queues and surface uncertain expired native attempts."""
    current = now or utc_now()
    begin_mutation(conn)
    changed: list[LaunchRecord] = []
    try:
        for launch in list_launches(conn, limit=500):
            if launch.state not in {
                "queued",
                "assigned",
                "launching",
                "awaiting_registration",
            }:
                continue
            deadline_passed = parse_time(current) >= parse_time(launch.deadline_at)
            if launch.state == "launching":
                p = marker(conn)
                row = conn.execute(
                    "SELECT started_at FROM session_launch_attempts "
                    f"WHERE launch_id = {p} AND completed_at IS NULL "
                    "ORDER BY attempt_number DESC LIMIT 1",
                    (launch.launch_id,),
                ).fetchone()
                lease_passed = bool(row) and parse_time(current) >= parse_time(
                    add_seconds(str(value(row, "started_at", 0)), LAUNCH_LEASE_SECONDS)
                )
                if deadline_passed or lease_passed:
                    changed.append(
                        update_launch(
                            conn,
                            launch.launch_id,
                            state="outcome_unknown",
                            result_code="launch_lease_expired",
                        )
                    )
            elif deadline_passed:
                final_state = (
                    "failed" if launch.state == "awaiting_registration" else "expired"
                )
                changed.append(
                    update_launch(
                        conn,
                        launch.launch_id,
                        state=final_state,
                        completed_at=current,
                        result_code=(
                            "registration_deadline"
                            if final_state == "failed"
                            else "launch_deadline"
                        ),
                    )
                )
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise


__all__ = ["settle_launch_deadlines"]
