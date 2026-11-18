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
Re-attaching while created with ``deployment_runs.add_item`` clears the entry on
that run only: the operator reversed the decision there, and a stale exclusion
would silently drop the item from the run it was just attached to.

A takeover successor honors pre-start operator parks on every run it takes
over until the item lands again or becomes the successor's member (an operator
adds it back); predecessor entries are never erased, so they stay the audit
record. Removals at item QA, transfers (``transferred_to_run_id``), set-asides
and automatic lineage releases leave a successor free to enroll the candidate
it carries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, NamedTuple

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_run_proposed_membership import run_items
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


def _predecessor_operator_removals(
    conn: Any, run_id: str
) -> list[tuple[str, datetime | None, dict[str, Any]]]:
    """Operator removals on every run *run_id* took over, with their run.

    A takeover marks both the run it supersedes and each never-started run it
    absorbs ``superseded_by_run_id`` = *run_id* before enrollment reads this,
    so walking that column back covers them all and their own predecessors.
    """
    from yoke_core.domain.deployment_member_candidate_release import (
        CORRECTION_RELEASE_REASON,
    )
    from yoke_core.domain.deployment_run_member_removal import (
        REOPENED_REASON,
        REPLACED_REASON,
    )
    from yoke_core.domain.deployment_run_member_set_aside import SET_ASIDE_REASON

    awaiting_later_release = {
        SET_ASIDE_REASON,
        CORRECTION_RELEASE_REASON,
        REPLACED_REASON,
        REOPENED_REASON,
    }

    if not _column_exists(conn, "deployment_runs", "superseded_by_run_id"):
        return []
    rows = conn.execute(
        "WITH RECURSIVE chain(id) AS (SELECT id FROM deployment_runs "
        "WHERE superseded_by_run_id=%s UNION SELECT r.id FROM deployment_runs r "
        "JOIN chain c ON r.superseded_by_run_id=c.id) "
        f"SELECT r.id,r.{MEMBERSHIP_REMOVALS_FIELD},"
        # Composition freezes at the first start, while resume can restamp started_at.
        "COALESCE(r.composition_frozen_at,r.started_at) "
        "FROM deployment_runs r JOIN chain c ON r.id=c.id",
        (run_id,),
    ).fetchall()
    return [
        (str(row[0]), row[2], entry)
        for row in rows
        for entry in parse_membership_removals(row[1], str(row[0]))
        if not entry.get("transferred_to_run_id")
        and entry.get("reason") not in awaiting_later_release
    ]


class InheritedExclusion(NamedTuple):
    """A predecessor's pre-start operator park this run still honors.

    It expires when the item lands again after ``removed_at``, or when an
    operator adds the item to this run, which makes it a member here.
    """

    item_id: int
    source_run_id: str
    reason: str
    removed_at: str


def inherited_exclusions(conn: Any, run_id: str) -> tuple[InheritedExclusion, ...]:
    """Predecessor parks still in effect on *run_id*, newest park per item."""
    parks: dict[int, InheritedExclusion] = {}
    for source, started_at, entry in _predecessor_operator_removals(conn, run_id):
        removed_at = parse_instant(entry["removed_at"])
        if started_at is not None and removed_at > parse_instant(started_at):
            continue
        item_id = int(entry["item_id"])
        held = parks.get(item_id)
        if held is None or parse_instant(held.removed_at) < removed_at:
            parks[item_id] = InheritedExclusion(
                item_id,
                source,
                str(entry.get("reason") or "no reason recorded"),
                str(entry["removed_at"]),
            )
    if not parks:
        return ()
    members = {
        int(row[0])
        for row in conn.execute(
            f"SELECT item_id FROM {run_items()} WHERE run_id=%s", (run_id,)
        ).fetchall()
    }
    landings = {
        int(row[0]): parse_instant(row[1])
        for row in conn.execute(
            "SELECT id,COALESCE(merge_queue_landed_at,merged_at) FROM items "
            "WHERE id=ANY(%s)",
            (sorted(parks),),
        ).fetchall()
        if row[1] is not None
    }
    return tuple(
        park
        for item_id, park in sorted(parks.items())
        if item_id not in members
        and (
            item_id not in landings
            or landings[item_id] <= parse_instant(park.removed_at)
        )
    )


def enrollment_removed_item_ids(conn: Any, run_id: str) -> frozenset[int]:
    """This run's removals plus any predecessor parks still in effect."""
    return removed_item_ids(conn, run_id) | frozenset(
        park.item_id for park in inherited_exclusions(conn, run_id)
    )


def _write(conn: Any, run_id: str, entries: list[dict[str, Any]]) -> None:
    conn.execute(
        f"UPDATE deployment_runs SET {MEMBERSHIP_REMOVALS_FIELD}=%s WHERE id=%s",
        (dumps_compact(entries) if entries else None, run_id),
    )


def record_membership_removals(
    conn: Any,
    run_id: str,
    item_ids: Iterable[int],
    *,
    reason: str,
    session_id: str | None,
    actor_id: int | None,
    transferred_to_run_id: str | None = None,
) -> str:
    """Record these removals in the caller's transaction, replacing earlier ones.

    Returns the ``removed_at`` stamp every new entry carries.
    """
    if not _column_exists(conn, "deployment_runs", MEMBERSHIP_REMOVALS_FIELD):
        raise ValueError(
            f"deployment_runs.{MEMBERSHIP_REMOVALS_FIELD} is not converged on "
            "this database; restart the serving API so its boot converge adds "
            "the column, then retry the removal"
        )
    removed = sorted({int(item_id) for item_id in item_ids})
    removed_at = iso8601_now()
    entries = [
        entry
        for entry in membership_removals(conn, run_id)
        if int(entry["item_id"]) not in removed
    ]
    entries.extend(
        {
            "item_id": item_id,
            "reason": reason,
            "removed_at": removed_at,
            "session_id": session_id,
            "actor_id": actor_id,
            **({"transferred_to_run_id": transferred_to_run_id} if transferred_to_run_id else {}),
        }
        for item_id in removed
    )
    _write(conn, run_id, entries)
    return removed_at


def clear_membership_removal(conn: Any, run_id: str, item_id: int) -> bool:
    """Drop *item_id*'s removal on *run_id* only; report whether one existed.

    Predecessor entries stay as the audit record of what was decided there;
    the item's membership here is what ends their inherited effect.
    """
    entries = membership_removals(conn, run_id)
    kept = [entry for entry in entries if int(entry["item_id"]) != int(item_id)]
    if len(kept) == len(entries):
        return False
    _write(conn, run_id, kept)
    return True


__all__ = [
    "InheritedExclusion",
    "MEMBERSHIP_REMOVALS_FIELD",
    "clear_membership_removal",
    "enrollment_removed_item_ids",
    "inherited_exclusions",
    "membership_removals",
    "record_membership_removals",
    "removed_item_ids",
]
