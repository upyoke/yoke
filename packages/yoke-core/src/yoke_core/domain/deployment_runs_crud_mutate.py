"""Mutation-side CRUD for deployment runs.

Owns the write paths: ``cmd_next_id``, ``cmd_create_run``, ``cmd_add_item``,
``cmd_remove_item``, ``cmd_update``. ``cmd_update`` carries the full
status-transition validation logic preserved verbatim — auto-set ``started_at``
on ``executing``, auto-set ``completed_at`` on terminal states, reject
``succeeded`` when ``current_stage`` ends in ``-failed`` or is not the final
flow stage.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now, query_scalar
from yoke_core.domain.deployment_runs_schema import (
    UPDATABLE_FIELDS,
    VALID_STATUSES,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.deployment_flow_state import require_flow_for_new_run
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_item,
    validate_deployment_run_items,
)

_RUN_MEMBERSHIP_LOCK_RETRIES = 5


def _lock_run(conn, run_id: str) -> Optional[str]:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT status FROM deployment_runs WHERE id=%s{suffix}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0])


def _require_composable_run(conn, run_id: str) -> None:
    status = _lock_run(conn, run_id)
    if status is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    if status != "created":
        raise ValueError(
            f"deployment run '{run_id}' is {status}; membership is mutable "
            "only while status='created'"
        )


def _run_item_ids(conn, run_id: str) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return tuple(
        int(row["item_id"]) if hasattr(row, "keys") else int(row[0]) for row in rows
    )


def _lock_run_with_stable_membership(
    conn,
    run_id: str,
) -> tuple[Optional[str], tuple[int, ...]]:
    """Lock workflow bindings before the run and reject a stale member snapshot."""
    for _attempt in range(_RUN_MEMBERSHIP_LOCK_RETRIES):
        item_ids = _run_item_ids(conn, run_id)
        lock_item_workflow_bindings(conn, item_ids)
        status = _lock_run(conn, run_id)
        if status is None:
            return None, ()
        if _run_item_ids(conn, run_id) == item_ids:
            return status, item_ids
        conn.rollback()
    raise RuntimeError(
        f"deployment run '{run_id}' membership changed repeatedly while locking"
    )


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
    lineage.require_lineage_for_stages(
        stages, release_lineage, flow=flow)


def cmd_create_run(
    project: str,
    flow: str,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
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
        _flow_project_id, target_tier, target_environment_id = (
            require_flow_for_new_run(
                conn,
                flow,
                project_id=project_id,
            )
        )
        if environment:
            from yoke_core.domain.environment_delivery_record import (
                require_registered_environment,
            )

            target_tier = "persistent"
            target_environment_id = require_registered_environment(
                conn, project_id, environment,
            )

        _refuse_run_that_cannot_execute(conn, flow, release_lineage)

        # Allocation and insertion share this serialized transaction. The
        # standalone next-id command remains a non-reserving preview.
        run_id = _next_run_id(conn, datetime.now(timezone.utc))

        inserted = conn.execute(
            "INSERT INTO deployment_runs "
            "(id, project_id, flow, target_tier, target_environment_id, "
            "release_lineage, created_by, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (
                run_id,
                project_id,
                flow,
                target_tier or None,
                target_environment_id or None,
                release_lineage or None,
                created_by,
                iso8601_now(),
            ),
        ).fetchone()
        if inserted is None:
            raise RuntimeError(f"deployment run ID {run_id} was claimed concurrently")
        conn.commit()
        return run_id
    finally:
        conn.close()


def cmd_add_item(run_id: str, item_id: int, db_path: Optional[str] = None) -> str:
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
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, %s)",
            (run_id, item_id, iso8601_now()),
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

    Auto-sets started_at when transitioning to executing and completed_at
    when transitioning to terminal states. Validates status values and
    cross-field consistency for status=succeeded.
    """
    if field not in UPDATABLE_FIELDS:
        return f"Error: field '{field}' is not updatable"

    conn = connect(db_path)
    try:
        if field == "status":
            status, item_ids = _lock_run_with_stable_membership(conn, run_id)
            if status is None:
                return f"Error: deployment run '{run_id}' not found"
            if value not in VALID_STATUSES:
                return f"Error: invalid status '{value}'"
            if value in {"created", "executing"}:
                try:
                    validate_deployment_run_items(
                        conn,
                        run_id=run_id,
                        item_ids=item_ids,
                    )
                except ValueError as exc:
                    return f"Error: {exc}"

            # Cross-field consistency guard for status=succeeded
            if value == "succeeded":
                cur_stage = (
                    query_scalar(
                        conn,
                        "SELECT COALESCE(current_stage, '') FROM deployment_runs WHERE id=%s",
                        (run_id,),
                    )
                    or ""
                )

                if cur_stage:
                    # Reject if current_stage ends in '-failed'
                    if cur_stage.endswith("-failed"):
                        if not force:
                            return (
                                f"Error: cannot set status=succeeded -- "
                                f"current_stage '{cur_stage}' indicates failure"
                            )

                    # Reject if current_stage doesn't match final flow stage
                    run_flow = query_scalar(
                        conn,
                        "SELECT flow FROM deployment_runs WHERE id=%s",
                        (run_id,),
                    )
                    if run_flow:
                        stages_json = query_scalar(
                            conn,
                            "SELECT stages FROM deployment_flows WHERE id=%s",
                            (run_flow,),
                        )
                        if stages_json:
                            try:
                                stages = json.loads(stages_json)
                                if stages:
                                    final_stage = stages[-1].get("name", "")
                                    if (
                                        final_stage
                                        and cur_stage != final_stage
                                        and cur_stage != "complete"
                                        and not force
                                    ):
                                        return (
                                            f"Error: cannot set status=succeeded -- "
                                            f"current_stage '{cur_stage}' is not the final stage"
                                        )
                            except (json.JSONDecodeError, IndexError, KeyError):
                                pass

            # Auto-set started_at when transitioning to executing
            if value == "executing":
                conn.execute(
                    "UPDATE deployment_runs SET status=%s, started_at=%s WHERE id=%s",
                    (value, iso8601_now(), run_id),
                )
                conn.commit()
                return None

            # Auto-set completed_at when transitioning to terminal states
            if value in ("succeeded", "failed", "cancelled"):
                completed_at = iso8601_now()
                conn.execute(
                    "UPDATE deployment_runs SET status=%s, completed_at=%s WHERE id=%s",
                    (value, completed_at, run_id),
                )
                if value == "succeeded":
                    from yoke_core.domain.environment_delivery_record import (
                        stamp_run_environment,
                    )
                    stamp_run_environment(conn, run_id, when=completed_at)
                conn.commit()
                return None
        elif _lock_run(conn, run_id) is None:
            return f"Error: deployment run '{run_id}' not found"

        conn.execute(
            f"UPDATE deployment_runs SET {field}=%s WHERE id=%s",
            (value, run_id),
        )
        conn.commit()
        return None
    finally:
        conn.close()
