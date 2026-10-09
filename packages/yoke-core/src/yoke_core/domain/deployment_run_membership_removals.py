"""Members released from a deployment run, and why.

Enrollment completes a run's membership from the code its candidate carries,
so deleting a membership row alone is undone by the next composition pass:
the same carried range proposes the same item and enrollment admits it again.
A removal is therefore a recorded decision, not a missing row. It lives on the
run as ``membership_removals`` -- one entry per item with the reason, when, and
who -- and every composition reader subtracts it: enrollment never re-admits
it, the omitted-work invariant does not demand it back, and the composition
notice names it beside the other members this run skipped.

Removing a member does not remove its code. The candidate still ships the
landing; the item simply is not this run's to close. Because no run holds it,
the next release's unheld-custody pass enrolls it again, which is where an item
removed for being in rework belongs once it returns to its release stage.

Removal also releases outstanding run-bound QA at independent item QA, or
a failed member whose recorded merge is outside its frozen project candidate,
or a replaced candidate at settlement, without closing it.
Re-attaching while created with ``deployment_runs.add_item`` clears the entry: the
operator reversed the decision, and a stale exclusion would silently drop the
item from the run it was just attached to.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.schema_common import _column_exists


MEMBERSHIP_REMOVALS_FIELD = "membership_removals"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def membership_removals(conn: Any, run_id: str) -> tuple[dict[str, Any], ...]:
    """Every recorded removal on *run_id*, in the order it was made.

    A database that has not converged the column yet has recorded nothing,
    so it answers empty rather than refusing a composition read.
    """
    if not _column_exists(conn, "deployment_runs", MEMBERSHIP_REMOVALS_FIELD):
        return ()
    row = conn.execute(
        f"SELECT {MEMBERSHIP_REMOVALS_FIELD} FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return ()
    return parse_membership_removals(_cell(row, MEMBERSHIP_REMOVALS_FIELD, 0), run_id)


def parse_membership_removals(value: Any, run_id: str) -> tuple[dict[str, Any], ...]:
    """Decode the durable removal record for composition and presentation."""
    stored = value if isinstance(value, list) else loads_text(value or "[]")
    if not isinstance(stored, list):
        raise ValueError(
            f"deployment run {run_id!r} has an unreadable "
            f"{MEMBERSHIP_REMOVALS_FIELD} record; repair it to a JSON array"
        )
    return tuple(dict(entry) for entry in stored if isinstance(entry, dict))


def removed_item_ids(conn: Any, run_id: str) -> frozenset[int]:
    """Item ids this run was told not to deliver."""
    return frozenset(
        int(entry["item_id"]) for entry in membership_removals(conn, run_id)
    )


def _write(conn: Any, run_id: str, entries: list[dict[str, Any]]) -> None:
    conn.execute(
        f"UPDATE deployment_runs SET {MEMBERSHIP_REMOVALS_FIELD}=%s WHERE id=%s",
        (dumps_compact(entries) if entries else None, run_id),
    )


def record_membership_removal(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    reason: str,
    session_id: str | None,
    actor_id: int | None,
) -> None:
    """Record one removal in the caller's transaction, replacing any earlier one."""
    if not _column_exists(conn, "deployment_runs", MEMBERSHIP_REMOVALS_FIELD):
        raise ValueError(
            f"deployment_runs.{MEMBERSHIP_REMOVALS_FIELD} is not converged on "
            "this database; restart the serving API so its boot converge adds "
            "the column, then retry the removal"
        )
    entries = [
        entry
        for entry in membership_removals(conn, run_id)
        if int(entry["item_id"]) != int(item_id)
    ]
    entries.append(
        {
            "item_id": int(item_id),
            "reason": reason,
            "removed_at": iso8601_now(),
            "session_id": session_id,
            "actor_id": actor_id,
        }
    )
    _write(conn, run_id, entries)


def clear_membership_removal(conn: Any, run_id: str, item_id: int) -> bool:
    """Drop *item_id*'s removal in the caller's transaction; report whether one existed."""
    entries = list(membership_removals(conn, run_id))
    kept = [entry for entry in entries if int(entry["item_id"]) != int(item_id)]
    if len(kept) == len(entries):
        return False
    _write(conn, run_id, kept)
    return True


__all__ = [
    "MEMBERSHIP_REMOVALS_FIELD",
    "clear_membership_removal",
    "membership_removals",
    "record_membership_removal",
    "removed_item_ids",
]
