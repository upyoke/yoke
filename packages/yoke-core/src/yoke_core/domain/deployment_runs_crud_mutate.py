"""Run creation, membership mutation, transitions, and success bookkeeping."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain import deployment_run_lineage_rebind as lineage_rebind
from yoke_core.domain import (
    deployment_run_completion_preconditions as completion_preconditions,
)
from yoke_core.domain.deployment_runs_schema import (
    UPDATABLE_FIELDS,
    VALID_STATUSES,
)
from yoke_core.domain.deployment_run_insert import insert_run
from yoke_core.domain.deployment_run_composition_guard import (
    frozen_mutation_refusal,
    has_frozen_composition,
    mutable_field_refusal,
    terminal_run_refusal,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.deployment_flow_state import require_flow_for_new_run
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


def cmd_next_id(db_path: Optional[str] = None) -> str:
    """Preview the next run ID for today without reserving it."""
    conn = connect(db_path)
    try:
        return _next_run_id(conn, datetime.now(timezone.utc))
    finally:
        conn.close()


def _next_run_id(conn, now: datetime) -> str:
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


def _refuse_run_that_cannot_execute(
    conn, flow: str, release_lineage: Optional[str]
) -> None:
    """Apply the dispatch stage's lineage requirement at creation time."""
    from yoke_core.domain import deployment_run_lineage_requirement as lineage
    from yoke_core.domain.json_helper import loads_text

    row = conn.execute(
        "SELECT stages FROM deployment_flows WHERE id = %s", (flow,)
    ).fetchone()
    stages = loads_text(row[0]) if row and row[0] else []
    lineage.require_lineage_for_stages(stages, release_lineage, flow=flow)


def cmd_create_run(
    project: str,
    flow: str,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    artifact_identity: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Create a new deployment run. Returns the generated run ID.

    ``environment`` (a registered name) overrides the flow's registered
    target; tier and environment otherwise copy from the flow definition.
    """
    conn = connect(db_path)
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute("LOCK TABLE deployment_runs IN SHARE ROW EXCLUSIVE MODE")
        project_id = resolve_project_id(conn, project)
        _flow_project_id, target_tier, target_environment_id = require_flow_for_new_run(
            conn,
            flow,
            project_id=project_id,
        )
        if environment:
            from yoke_core.domain.environment_delivery_record import (
                require_registered_environment,
            )

            target_tier = "persistent"
            target_environment_id = require_registered_environment(
                conn,
                project_id,
                environment,
            )

        _refuse_run_that_cannot_execute(conn, flow, release_lineage)

        # Allocation and insertion share this serialized transaction. The
        # standalone next-id command remains a non-reserving preview.
        run_id = _next_run_id(conn, datetime.now(timezone.utc))

        inserted = insert_run(
            conn,
            run_id=run_id,
            project_id=project_id,
            flow=flow,
            target_tier=target_tier,
            target_environment_id=target_environment_id,
            release_lineage=release_lineage,
            created_by=created_by,
            created_at=iso8601_now(),
            artifact_identity=artifact_identity,
        )
        if inserted is None:
            raise RuntimeError(f"deployment run ID {run_id} was claimed concurrently")
        conn.commit()
        return run_id
    finally:
        conn.close()


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
