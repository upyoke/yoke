"""Write a set of run members' concrete selections and snapshots at once.

A member with no stored requirement selection derives one from its
outstanding post-deploy obligations now; a stored selection is frozen
exactly as given. Every member is snapshotted from one read of the mutable
QA facts and written back in one statement, so the cost does not grow with
the member count.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_member_post_deploy_admission import (
    post_deploy_admission_sets,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_members_requirements,
)


def read_member_snapshots(
    conn: Any, run_id: str, stored: Mapping[int, Any], *, lock: bool = True
) -> tuple[dict[int, str], dict[int, str]]:
    """Each member's concrete selection and snapshot, without writing either.

    *stored* maps each member to its stored ``requirement_selection``.
    ``lock=False`` reads before the run lock; the caller then locks the
    snapshot's rows (:func:`snapshot_row_ids`) and proves them unchanged.
    """
    selections = {int(item_id): str(value or "") for item_id, value in stored.items()}
    if not selections:
        return {}, {}
    derived = [item_id for item_id, value in selections.items() if not value.strip()]
    for item_id, (admitted, _unadmitted) in post_deploy_admission_sets(
        conn, run_id=run_id, item_ids=derived
    ).items():
        selections[item_id] = requirement_selection(requirement_ids=admitted)
    snapshots = snapshot_members_requirements(
        conn, run_id=run_id, selections=selections, lock=lock
    )
    return selections, snapshots


def snapshot_row_ids(
    selections: Mapping[int, str], snapshots: Mapping[int, str]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The requirement and plan ids a set of snapshots selected and froze."""
    requirements: set[int] = set()
    plans: set[int] = set()
    for item_id, snapshot in snapshots.items():
        selected = json.loads(selections[item_id] or "{}")
        requirements.update(
            int(value) for value in selected.get("requirement_ids") or ()
        )
        plans.update(int(value) for value in selected.get("plan_ids") or ())
        plans.update(
            int(entry["plan"]["id"])
            for entry in json.loads(snapshot).get("plans") or ()
        )
    return tuple(sorted(requirements)), tuple(sorted(plans))


def store_member_snapshots(
    conn: Any,
    run_id: str,
    selections: Mapping[int, str],
    snapshots: Mapping[int, str],
    *,
    intents: Mapping[int, str | None] | None = None,
) -> None:
    """Write members' selections and snapshots, and *intents* when given."""
    if not selections:
        return
    ids = list(selections)
    intent_sql = "delivery_intent=m.intent," if intents is not None else ""
    conn.execute(
        f"UPDATE deployment_run_items dri SET {intent_sql}"
        "requirement_selection=m.selection,requirement_snapshot=m.snapshot "
        "FROM unnest(%s::bigint[],%s::text[],%s::text[],%s::text[]) "
        "AS m(item_id,intent,selection,snapshot) "
        "WHERE dri.run_id=%s AND dri.item_id=m.item_id",
        (
            ids,
            [(intents or {}).get(item_id) for item_id in ids],
            [selections[item_id] for item_id in ids],
            [snapshots[item_id] for item_id in ids],
            run_id,
        ),
    )


def write_member_snapshots(
    conn: Any,
    run_id: str,
    stored: Mapping[int, Any],
    *,
    intents: Mapping[int, str | None] | None = None,
) -> None:
    """Freeze each member's selection and snapshot; write *intents* when given.

    *stored* maps each member to its stored ``requirement_selection``.
    """
    selections, snapshots = read_member_snapshots(conn, run_id, stored)
    store_member_snapshots(conn, run_id, selections, snapshots, intents=intents)


__all__ = [
    "read_member_snapshots",
    "snapshot_row_ids",
    "store_member_snapshots",
    "write_member_snapshots",
]
