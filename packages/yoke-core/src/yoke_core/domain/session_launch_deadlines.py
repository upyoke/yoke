"""Deadline convergence for queued and in-flight session launches."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_store import (
    LAUNCH_COLUMNS,
    add_seconds,
    begin_mutation,
    marker,
    parse_time,
    row_to_launch,
    update_launch,
    utc_now,
    value,
)
from yoke_core.domain.session_launch_types import LAUNCH_LEASE_SECONDS, LaunchRecord


def _deadline_candidates(
    conn: Any,
    *,
    launch_id: str | None,
    project_id: int | None,
) -> list[LaunchRecord]:
    p = marker(conn)
    where = ["state IN ('queued','assigned','launching','awaiting_registration')"]
    params: list[Any] = []
    if launch_id is not None:
        where.append(f"launch_id = {p}")
        params.append(launch_id)
    if project_id is not None:
        where.append(f"project_id = {p}")
        params.append(project_id)
    lock = " FOR UPDATE SKIP LOCKED" if db_backend.connection_is_postgres(conn) else ""
    rows = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches "
        f"WHERE {' AND '.join(where)} ORDER BY deadline_at, launch_id{lock}",
        tuple(params),
    ).fetchall()
    return [row_to_launch(row) for row in rows]


def settle_launch_deadlines(
    conn: Any,
    *,
    now: str | None = None,
    launch_id: str | None = None,
    project_id: int | None = None,
) -> list[LaunchRecord]:
    """Close expired queues and surface uncertain expired native attempts."""
    current = now or utc_now()
    begin_mutation(conn)
    changed: list[LaunchRecord] = []
    try:
        for launch in _deadline_candidates(
            conn,
            launch_id=launch_id,
            project_id=project_id,
        ):
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
                            delivery_changed_at=current,
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
