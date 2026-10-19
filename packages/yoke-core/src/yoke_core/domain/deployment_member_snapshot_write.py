"""Write a set of run members' concrete selections and snapshots at once.

A member with no stored requirement selection derives one from its
outstanding post-deploy obligations now; a stored selection is frozen
exactly as given. Every member is snapshotted from one read of the mutable
QA facts and written back in one statement, so the cost does not grow with
the member count.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_member_post_deploy_admission import (
    post_deploy_admission_sets,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_members_requirements,
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
    if not stored:
        return
    selections = {int(item_id): str(value or "") for item_id, value in stored.items()}
    derived = [item_id for item_id, value in selections.items() if not value.strip()]
    for item_id, (admitted, _unadmitted) in post_deploy_admission_sets(
        conn, run_id=run_id, item_ids=derived
    ).items():
        selections[item_id] = requirement_selection(requirement_ids=admitted)
    snapshots = snapshot_members_requirements(
        conn, run_id=run_id, selections=selections
    )
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


__all__ = ["write_member_snapshots"]
