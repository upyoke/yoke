"""Re-land attempts: a new pull request for an item that already landed.

An item's ``merge_queue_*`` columns name its current landing. Items re-land
routinely — a fix-up, a revert — and the pull request for that second landing
used to overwrite the first before anything merged: a revert pull request
closed unmerged left the item pointing at a pull request that never landed,
with no landing at all.

So a pull request opened for an item that already has a landing is recorded
here instead, keyed by item and pull request. The item's columns move to it
only when the landing observer sees it merge
(:func:`yoke_core.domain.merge_queue_landing_marker.promote_landing_attempt`).
One that closes unmerged is closed with its reason and the item keeps the
landing it had. At most one attempt per item is open; a newer pull request
closes the older one as superseded.

Readers that describe an in-flight landing — the board label, the fleet
landing readback, the landing observer and its waiter — read the open
attempt first and the item's columns otherwise. Readers of delivered state
keep reading the item's columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_types import row_dict


#: Why an attempt closed. Stored verbatim on the attempt record.
MERGED_REASON = "merged; promoted to the item's current landing"


def superseded_reason(pr_number: str) -> str:
    return f"superseded by pull request {pr_number}"


def closed_unmerged_reason(pr_number: str) -> str:
    return (
        f"pull request {pr_number} closed without merging; "
        "the item keeps its previous landing"
    )


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _instant(value: Any) -> datetime | None:
    return parse_instant(value) if value not in (None, "") else None


def item_has_landing(conn: Any, item_id: int) -> bool:
    """Whether the item already landed once, so a new pull request is an attempt.

    ``merged_at`` survives close-out clearing the queue marker, so an item
    reopened after done still counts as landed.
    """
    p = _p(conn)
    row = conn.execute(
        "SELECT 1 FROM items WHERE id=" + p + " AND (merged_at IS NOT NULL "
        "OR merge_queue_landed_at IS NOT NULL)",
        (int(item_id),),
    ).fetchone()
    return row is not None


def _attempt(row: Any) -> dict[str, Any]:
    value = row_dict(row)
    return {
        "pr_number": str(value["pr_number"]),
        "enqueued_at": _instant(value.get("enqueued_at")),
        "opened_at": _instant(value.get("opened_at")),
        "closed_at": _instant(value.get("closed_at")),
        "closed_reason": str(value.get("closed_reason") or ""),
    }


_COLUMNS = "pr_number,enqueued_at,opened_at,closed_at,closed_reason"


def read_open_attempt(conn: Any, item_id: int) -> dict[str, Any] | None:
    """The item's in-flight re-land attempt, or ``None``."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM merge_queue_landing_attempts "
        f"WHERE item_id={p} AND closed_at IS NULL",
        (int(item_id),),
    ).fetchone()
    return _attempt(row) if row is not None else None


def read_latest_attempt(conn: Any, item_id: int) -> dict[str, Any] | None:
    """The open attempt, else the most recently closed one with its reason."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM merge_queue_landing_attempts WHERE item_id={p} "
        "ORDER BY CASE WHEN closed_at IS NULL THEN 0 ELSE 1 END, "
        "closed_at DESC, opened_at DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    return _attempt(row) if row is not None else None


def close_attempt(
    conn: Any,
    item_id: int,
    pr_number: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Close one open attempt with ``reason``; the caller owns the commit."""
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE merge_queue_landing_attempts SET closed_at={p}, closed_reason={p} "
        f"WHERE item_id={p} AND pr_number={p} AND closed_at IS NULL",
        (
            instant_parameter(conn, utc_now() if now is None else parse_instant(now)),
            reason,
            int(item_id),
            str(pr_number),
        ),
    )
    return bool(cursor.rowcount)


def close_open_attempts(
    conn: Any, item_id: int, reason: str, *, now: datetime | None = None
) -> None:
    """Close whichever attempt is open for the item, if any."""
    attempt = read_open_attempt(conn, item_id)
    if attempt is not None:
        close_attempt(conn, item_id, attempt["pr_number"], reason, now=now)


def record_attempt(
    conn: Any,
    item_id: int,
    pr_number: str,
    *,
    enqueued_at: datetime | None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Open or refresh the attempt for ``pr_number``; return it and a reset flag.

    A supplied arming timestamp replaces the attempt's episode; ``None``
    preserves the open attempt's. A pull request recorded again after its
    attempt closed (reopened on GitHub) reopens that record. The flag says
    whether the stored landing observation describes a different landing
    episode and must go. The caller owns the commit.
    """
    current = utc_now() if now is None else parse_instant(now)
    open_attempt = read_open_attempt(conn, item_id)
    if open_attempt is not None and open_attempt["pr_number"] != pr_number:
        close_attempt(
            conn,
            item_id,
            open_attempt["pr_number"],
            superseded_reason(pr_number),
            now=current,
        )
        open_attempt = None
    same = open_attempt is not None
    previous = open_attempt["enqueued_at"] if same else None
    episode = enqueued_at if enqueued_at is not None else previous
    p = _p(conn)
    conn.execute(
        "INSERT INTO merge_queue_landing_attempts "
        "(item_id,project_id,pr_number,enqueued_at,opened_at,closed_at,closed_reason) "
        f"SELECT id,project_id,{p},{p},{p},NULL,'' FROM items WHERE id={p} "
        "ON CONFLICT(item_id,pr_number) DO UPDATE SET "
        "enqueued_at=excluded.enqueued_at, closed_at=NULL, closed_reason='', "
        "opened_at=CASE WHEN merge_queue_landing_attempts.closed_at IS NULL "
        "THEN merge_queue_landing_attempts.opened_at ELSE excluded.opened_at END",
        (
            str(pr_number),
            instant_parameter(conn, episode),
            instant_parameter(conn, current),
            int(item_id),
        ),
    )
    reset = not same or episode != previous
    attempt = read_open_attempt(conn, item_id)
    if attempt is None:
        raise LookupError(f"landing attempt not recorded: item {item_id} is absent")
    return attempt, reset


def write_attempt_episode(
    conn: Any,
    item_id: int,
    pr_number: str,
    *,
    value: datetime | None,
    expected: datetime | None,
) -> bool:
    """Compare-and-set the open attempt's arming episode.

    ``expected=None`` writes only over an empty episode; otherwise only over
    that exact episode, so a concurrent re-arm keeps its fresh one.
    """
    p = _p(conn)
    guard = "AND enqueued_at IS NULL" if expected is None else f"AND enqueued_at={p}"
    params: tuple[Any, ...] = (
        instant_parameter(conn, value),
        int(item_id),
        str(pr_number),
    )
    if expected is not None:
        params += (instant_parameter(conn, expected),)
    cursor = conn.execute(
        f"UPDATE merge_queue_landing_attempts SET enqueued_at={p} "
        f"WHERE item_id={p} AND pr_number={p} AND closed_at IS NULL {guard}",
        params,
    )
    return bool(cursor.rowcount)


__all__ = [
    "MERGED_REASON",
    "close_attempt",
    "close_open_attempts",
    "closed_unmerged_reason",
    "item_has_landing",
    "read_latest_attempt",
    "read_open_attempt",
    "record_attempt",
    "superseded_reason",
    "write_attempt_episode",
]
