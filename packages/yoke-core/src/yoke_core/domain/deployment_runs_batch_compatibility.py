"""Pre-creation batch check, and the item labels composition refusals share.

``cmd_check_batch_compatibility`` runs the same project, delivery-readiness
and hard-block checks as ``cmd_validate_composition``, against a proposed
batch of items rather than a run's membership.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.deployment_run_reopened_members import unready_item_ids
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.item_ref_render import render_item_ref_lookup


def _not_delivery_ready(conn, rows, *, allow_completed: bool = False) -> list[str]:
    status_of = {int(item_id): status for item_id, status in rows}
    unready = unready_item_ids(conn, rows, allow_completed=allow_completed)
    ref = render_item_ref_lookup(conn, unready)
    return [f"{ref(item_id)} (status={status_of[item_id]})" for item_id in unready]


def cmd_check_batch_compatibility(
    project: str,
    flow: str,
    item_ids: Sequence[int],
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate proposed items before run creation. Returns (ok, message).

    Same checks as validate-composition but against a proposed batch of items.
    """
    if not item_ids:
        return False, "FAIL: No item IDs provided"

    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project)
        assert ident is not None
        _ = flow
        placeholders = ",".join("%s" for _ in item_ids)
        errors: List[str] = []

        wrong_project = query_rows(
            conn,
            f"SELECT i.id, p.slug "
            f"FROM items i "
            f"JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders}) AND i.project_id <> %s",
            tuple(item_ids) + (ident.id,),
        )
        if wrong_project:
            ref = render_item_ref_lookup(conn, (row[0] for row in wrong_project))
            items_str = ", ".join(
                f"{ref(row[0])} (project={row[1]})" for row in wrong_project
            )
            errors.append(f"Project mismatch (batch expects {ident.slug}): {items_str}")

        delivery_candidates = query_rows(
            conn,
            f"SELECT i.id, i.status FROM items i WHERE i.id IN ({placeholders})",
            tuple(item_ids),
        )
        not_passed = _not_delivery_ready(conn, delivery_candidates)
        if not_passed:
            errors.append(
                "Items not delivery-ready for their pinned workflow: "
                + ", ".join(not_passed)
            )

        blocked = unsatisfied_dependency_pairs(
            conn,
            item_ids,
            co_scheduled_blocker_ids=item_ids,
        )
        if blocked:
            ref = render_item_ref_lookup(
                conn, [i for d, b, _ in blocked for i in (d, b)]
            )
            items_str = ", ".join(
                f"{ref(dependent)} (blocked by {ref(blocker)}: {verdict.reason})"
                for dependent, blocker, verdict in blocked
            )
            errors.append(f"Unsatisfied hard-block dependencies: {items_str}")

        if errors:
            error_text = "\n".join(errors)
            return False, f"FAIL: Batch compatibility check failed:\n{error_text}"

        return True, "OK"
    finally:
        conn.close()


__all__ = ["cmd_check_batch_compatibility"]
