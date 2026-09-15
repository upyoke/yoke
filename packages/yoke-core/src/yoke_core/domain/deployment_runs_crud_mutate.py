"""Run creation, membership mutation, transitions, and success bookkeeping."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain import deployment_run_lineage_rebind as lineage_rebind
from yoke_core.domain import (
    deployment_run_completion_preconditions as completion_preconditions,
)
from yoke_core.domain.deployment_run_create_write import (
    cmd_create_run,
    cmd_next_id,
)
from yoke_core.domain.deployment_runs_schema import (
    UPDATABLE_FIELDS,
    VALID_STATUSES,
)
from yoke_core.domain.deployment_run_composition_guard import (
    frozen_mutation_refusal,
    has_frozen_composition,
    mutable_field_refusal,
    terminal_run_refusal,
)
from yoke_core.domain.deployment_runs_lock import lock_run, lock_run_with_stable_membership
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_item,
    validate_deployment_run_items,
)


def _require_composable_run(conn, run_id: str) -> None:
    status = lock_run(conn, run_id)
    if status is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    if status != "created":
        raise ValueError(
            f"deployment run '{run_id}' is {status}; membership is mutable "
            "only while status='created'"
        )
    if has_frozen_composition(conn, run_id):
        raise ValueError(frozen_mutation_refusal(run_id, "membership")[7:])


def cmd_add_item(
    run_id: str,
    item_id: int,
    db_path: Optional[str] = None,
    *,
    delivery_intent: Optional[str] = None,
    requirement_ids: Iterable[int] = (),
    plan_ids: Iterable[int] = (),
) -> str:
    """Add item to run. Returns confirmation message."""
    conn = connect(db_path)
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        _require_composable_run(conn, run_id)
        validate_deployment_run_item(
            conn,
            run_id=run_id,
            item_id=int(item_id),
        )
        from yoke_core.domain.deployment_requirement_snapshots import (
            requirement_selection,
            snapshot_member_requirements,
        )
        from yoke_core.domain.deployment_run_composition_freeze import (
            validate_delivery_intent_for_item,
        )

        intent = validate_delivery_intent_for_item(conn, int(item_id), delivery_intent)
        selection = requirement_selection(
            requirement_ids=requirement_ids, plan_ids=plan_ids
        )
        snapshot_member_requirements(
            conn, run_id=run_id, item_id=int(item_id), selection_json=selection
        )
        conn.execute(
            "INSERT INTO deployment_run_items "
            "(run_id, item_id, added_at, delivery_intent, requirement_selection) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run_id, item_id, iso8601_now(), intent, selection),
        )
        conn.commit()
        return f"Added item {item_id} to run {run_id}"
    finally:
        conn.close()


def cmd_remove_item(run_id: str, item_id: int, db_path: Optional[str] = None) -> str:
    """Remove item from run. Returns confirmation message."""
    conn = connect(db_path)
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        _require_composable_run(conn, run_id)
        conn.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (run_id, item_id),
        )
        conn.commit()
        return f"Removed item {item_id} from run {run_id}"
    finally:
        conn.close()


def cmd_update(
    run_id: str,
    field: str,
    value: str,
    force: bool = False,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Update a run column. Returns error message on failure, None on success.

    Auto-sets timestamps and validates status=succeeded cross-field consistency.
    """
    if field not in UPDATABLE_FIELDS:
        return f"Error: field '{field}' is not updatable"

    conn = connect(db_path)
    try:
        if field == "status":
            status, item_ids = lock_run_with_stable_membership(conn, run_id)
            if status is None:
                return f"Error: deployment run '{run_id}' not found"
            if value not in VALID_STATUSES:
                return f"Error: invalid status '{value}'"
            if refusal := terminal_run_refusal(
                run_id, status, advancing_to=value, action="change status"
            ):
                return refusal
            if value == "created" and has_frozen_composition(conn, run_id):
                return frozen_mutation_refusal(run_id, "status")
            if value in {"created", "executing"}:
                try:
                    validate_deployment_run_items(
                        conn,
                        run_id=run_id,
                        item_ids=item_ids,
                    )
                except ValueError as exc:
                    return f"Error: {exc}"

            if value == "succeeded" and (
                refusal := completion_preconditions.refuse_succeeded(
                    conn, run_id, force=force
                )
            ):
                return refusal

            if value == "executing":
                from yoke_core.domain.deployment_run_composition_freeze import (
                    freeze_run_composition,
                )

                freeze_run_composition(conn, run_id)
                conn.execute(
                    "UPDATE deployment_runs SET status=%s, started_at=%s WHERE id=%s",
                    (value, iso8601_now(), run_id),
                )
                conn.commit()
                return None

            if value in ("succeeded", "failed", "cancelled"):
                completed_at = iso8601_now()
                conn.execute(
                    "UPDATE deployment_runs SET status=%s, completed_at=%s WHERE id=%s",
                    (value, completed_at, run_id),
                )
                if value == "succeeded":
                    from yoke_core.domain.deployment_run_carried_work import (
                        record_carried_work,
                    )
                    from yoke_core.domain.environment_delivery_record import (
                        stamp_run_environment,
                    )

                    stamp_run_environment(conn, run_id, when=completed_at)
                    record_carried_work(conn, run_id)
                conn.commit()
                return None
        elif field == lineage_rebind.LINEAGE_FIELD and (
            refusal := lineage_rebind.refuse_lineage_write(conn, run_id, value)
        ):
            return refusal
        else:
            status = lock_run(conn, run_id)
            if status is None:
                return f"Error: deployment run '{run_id}' not found"
            if field == "current_stage" and (
                refusal := terminal_run_refusal(
                    run_id, status, advancing_to=value, action="advance to a new stage"
                )
            ):
                return refusal
            if field in {"artifact_identity", "composition_resolution"} and (
                refusal := mutable_field_refusal(conn, run_id, field, status)
            ):
                return refusal

        conn.execute(
            f"UPDATE deployment_runs SET {field}=%s WHERE id=%s",
            (value, run_id),
        )
        conn.commit()
        return None
    finally:
        conn.close()


__all__ = [
    "cmd_add_item",
    "cmd_create_run",
    "cmd_next_id",
    "cmd_remove_item",
    "cmd_update",
]
