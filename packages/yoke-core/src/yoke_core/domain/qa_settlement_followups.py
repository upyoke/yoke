"""Close-outs a waived QA requirement owes, replayed off the request path.

Waiving a requirement can unblock a member's held close-out and the settling
run that member holds open. Replaying both inside the waive request walked
the runs' gates, checkouts and GitHub before the call could answer. The waive
now records the owed follow-up in the same transaction as the waiver, and
:mod:`yoke_core.domain.qa_settlement_followup_job` replays it.

A row stays until a replay of its latest request finishes. A replay that
raises keeps the row with its attempt count, time and error, and is retried
after :data:`RETRY_AFTER_SECONDS`; so does a row whose replaying process
died. ``yoke db read "SELECT * FROM qa_settlement_followups"`` names every
follow-up still owed and why.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, utc_now

_LOG = logging.getLogger(__name__)

#: How long a claimed row waits before another cycle may replay it again.
RETRY_AFTER_SECONDS = 60
CYCLE_LIMIT = 50

#: Part of the QA schema, which initializes on its own before ``items``
#: exists, so ``item_id`` carries no foreign key, like ``qa_requirements``.
QA_SETTLEMENT_FOLLOWUPS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS qa_settlement_followups (
  item_id INTEGER PRIMARY KEY,
  requested_at TIMESTAMPTZ NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  attempted_at TIMESTAMPTZ,
  last_error TEXT NOT NULL DEFAULT ''
);
"""


def request_settlement_followup(conn: Any, *, item_id: int) -> None:
    """Owe *item_id* its close-out replay, in the caller's transaction."""
    conn.execute(
        "INSERT INTO qa_settlement_followups (item_id, requested_at) "
        "VALUES (%s, %s) ON CONFLICT (item_id) "
        "DO UPDATE SET requested_at = EXCLUDED.requested_at",
        (int(item_id), instant_parameter(conn, utc_now())),
    )


def _claim(conn: Any, item_id: int, now: datetime) -> Any:
    """Take one row for this cycle; ``None`` when another cycle holds it."""
    cutoff = now - timedelta(seconds=RETRY_AFTER_SECONDS)
    row = conn.execute(
        "UPDATE qa_settlement_followups "
        "SET attempted_at = %s, attempts = attempts + 1 "
        "WHERE item_id = %s AND (attempted_at IS NULL OR attempted_at < %s) "
        "RETURNING requested_at",
        (instant_parameter(conn, now), int(item_id), instant_parameter(conn, cutoff)),
    ).fetchone()
    conn.commit()
    return None if row is None else row[0]


def _finish(conn: Any, item_id: int, requested_at: Any) -> None:
    """Drop the replayed request; a newer one stays, ready for the next cycle."""
    conn.execute(
        "DELETE FROM qa_settlement_followups WHERE item_id = %s AND requested_at = %s",
        (int(item_id), requested_at),
    )
    conn.execute(
        "UPDATE qa_settlement_followups SET attempted_at = NULL, attempts = 0, "
        "last_error = '' WHERE item_id = %s",
        (int(item_id),),
    )
    conn.commit()


def _record_failure(conn: Any, item_id: int, exc: Exception) -> None:
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 - the error below is the report
        pass
    conn.execute(
        "UPDATE qa_settlement_followups SET last_error = %s WHERE item_id = %s",
        (f"{type(exc).__name__}: {exc}", int(item_id)),
    )
    conn.commit()
    _LOG.warning(
        "settlement follow-up for item %s failed and will be retried: %s",
        item_id,
        exc,
    )


def replay_settlement_followups(
    conn: Any, *, now: datetime | None = None
) -> dict[str, list[int]]:
    """Replay every owed follow-up this cycle can claim."""
    from yoke_core.domain.deployment_member_close_out_retry import (
        after_record_settled,
    )

    current = utc_now() if now is None else now
    cutoff = current - timedelta(seconds=RETRY_AFTER_SECONDS)
    rows = conn.execute(
        "SELECT item_id FROM qa_settlement_followups "
        "WHERE attempted_at IS NULL OR attempted_at < %s "
        "ORDER BY requested_at LIMIT %s",
        (instant_parameter(conn, cutoff), CYCLE_LIMIT),
    ).fetchall()
    conn.commit()
    result: dict[str, list[int]] = {"replayed": [], "failed": []}
    for row in rows:
        item_id = int(row[0])
        requested_at = _claim(conn, item_id, current)
        if requested_at is None:
            continue
        try:
            after_record_settled(conn, item_id=item_id)
        except Exception as exc:  # noqa: BLE001 - kept on the row and retried
            _record_failure(conn, item_id, exc)
            result["failed"].append(item_id)
            continue
        _finish(conn, item_id, requested_at)
        result["replayed"].append(item_id)
    return result


__all__ = [
    "CYCLE_LIMIT",
    "QA_SETTLEMENT_FOLLOWUPS_CREATE_SQL",
    "RETRY_AFTER_SECONDS",
    "replay_settlement_followups",
    "request_settlement_followup",
]
