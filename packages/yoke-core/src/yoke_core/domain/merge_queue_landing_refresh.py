"""Server-side cadence shared by relay and waiter landing observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.github_poll_schedule import MINIMUM_POLL_INTERVAL_SECONDS
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
)


REFRESH_CADENCE_SECONDS = float(MINIMUM_POLL_INTERVAL_SECONDS)
LANDING_RECORD_STALE_SECONDS = REFRESH_CADENCE_SECONDS * 2.0


@dataclass(frozen=True)
class LandingRefresh:
    project_id: int
    started_at: str = ""
    completed_at: str = ""
    last_error: str = ""

    @property
    def in_progress(self) -> bool:
        return bool(self.started_at and not self.completed_at)

    def payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "last_error": self.last_error,
            "in_progress": self.in_progress,
        }


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def claim_due_projects(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime,
    cadence_seconds: float = REFRESH_CADENCE_SECONDS,
) -> tuple[int, ...]:
    """Atomically claim each project whose last sweep began before cadence."""
    current = timestamp(now)
    cutoff = timestamp(now - timedelta(seconds=float(cadence_seconds)))
    p = _p(conn)
    claimed: list[int] = []
    for project_id in sorted({int(value) for value in project_ids}):
        inserted = conn.execute(
            "INSERT INTO merge_queue_landing_refreshes "
            "(project_id,started_at,completed_at,last_error) "
            f"VALUES ({p},{p},NULL,'') ON CONFLICT(project_id) DO NOTHING",
            (project_id, current),
        )
        if inserted.rowcount:
            claimed.append(project_id)
            continue
        updated = conn.execute(
            "UPDATE merge_queue_landing_refreshes SET "
            f"started_at={p},completed_at=NULL,last_error='' "
            f"WHERE project_id={p} AND started_at<={p}",
            (current, project_id, cutoff),
        )
        if updated.rowcount:
            claimed.append(project_id)
    # Release the cadence row before GitHub I/O. Concurrent callers now see
    # this cycle and reuse its records instead of duplicating the project read.
    conn.commit()
    return tuple(claimed)


def complete_projects(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime,
) -> None:
    projects = tuple(sorted({int(value) for value in project_ids}))
    if not projects:
        return
    p = _p(conn)
    slots = ",".join(p for _ in projects)
    conn.execute(
        "UPDATE merge_queue_landing_refreshes SET "
        f"completed_at={p},last_error='' WHERE project_id IN ({slots})",
        (timestamp(now), *projects),
    )
    conn.commit()


def fail_projects(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime,
    error: str,
) -> None:
    projects = tuple(sorted({int(value) for value in project_ids}))
    if not projects:
        return
    p = _p(conn)
    slots = ",".join(p for _ in projects)
    conn.execute(
        "UPDATE merge_queue_landing_refreshes SET "
        f"completed_at={p},last_error={p} WHERE project_id IN ({slots})",
        (timestamp(now), str(error), *projects),
    )
    conn.commit()


def read_refresh(conn: Any, project_id: int) -> LandingRefresh:
    p = _p(conn)
    row = conn.execute(
        "SELECT project_id,started_at,completed_at,last_error "
        f"FROM merge_queue_landing_refreshes WHERE project_id={p}",
        (int(project_id),),
    ).fetchone()
    if row is None:
        return LandingRefresh(project_id=int(project_id))
    value = row_dict(row)
    return LandingRefresh(
        project_id=int(value["project_id"]),
        started_at=str(value.get("started_at") or ""),
        completed_at=str(value.get("completed_at") or ""),
        last_error=str(value.get("last_error") or ""),
    )


def record_age_seconds(observed_at: str, *, now: datetime) -> float | None:
    observed = parse_timestamp(observed_at)
    if observed is None:
        return None
    return max(0.0, (now - observed).total_seconds())


__all__ = [
    "LANDING_RECORD_STALE_SECONDS",
    "REFRESH_CADENCE_SECONDS",
    "LandingRefresh",
    "claim_due_projects",
    "complete_projects",
    "fail_projects",
    "read_refresh",
    "record_age_seconds",
]
