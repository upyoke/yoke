"""Allocate the date-sequenced id a new deployment run is created under."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from yoke_core.domain.db_helpers import connect, utc_now

#: Run ids are shared by every project, so two projects creating at once each
#: hold the id they picked until commit and the later one takes the next.
_RUN_ID_LOCK_SQL = (
    "SELECT pg_try_advisory_xact_lock(hashtext('deployment_runs.id'), hashtext(%s))"
)


def cmd_next_id(db_path: Optional[str] = None) -> str:
    """Preview the next run ID for today without reserving it."""
    conn = connect(db_path)
    try:
        return next_run_id(conn, utc_now())
    finally:
        conn.close()


def next_run_id(conn, now: datetime) -> str:
    """Return max numeric suffix + 1 for *now*'s UTC day."""
    today = now.astimezone(timezone.utc).strftime("%Y%m%d")
    prefix = f"run-{today}-"
    rows = conn.execute(
        "SELECT id FROM deployment_runs WHERE id LIKE %s",
        (f"{prefix}%",),
    ).fetchall()
    pattern = re.compile(rf"^{re.escape(prefix)}([0-9]+)$")
    suffixes = [
        int(match.group(1))
        for row in rows
        if (match := pattern.fullmatch(str(row[0]))) is not None
    ]
    return f"{prefix}{max(suffixes, default=0) + 1:03d}"


def reserve_run_id(conn, now: datetime) -> str:
    """Allocate the next free run id and hold it until this transaction ends.

    Another project's creation may hold an id it has not committed yet; the
    held id is skipped, and an id committed since the first read is too.
    """
    candidate = next_run_id(conn, now)
    while True:
        held = conn.execute(_RUN_ID_LOCK_SQL, (candidate,)).fetchone()[0]
        taken = conn.execute(
            "SELECT 1 FROM deployment_runs WHERE id=%s", (candidate,)
        ).fetchone()
        if held and taken is None:
            return candidate
        prefix, _, number = candidate.rpartition("-")
        candidate = f"{prefix}-{int(number) + 1:03d}"


__all__ = ["cmd_next_id", "next_run_id", "reserve_run_id"]
