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


def cmd_create_run(
    project: str,
    flow: str,
    target_env: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    db_path: Optional[str] = None,
) -> str:
    """Create a new deployment run. Returns the generated run ID."""
    conn = connect(db_path)
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute(
                "LOCK TABLE deployment_runs IN SHARE ROW EXCLUSIVE MODE"
            )
        project_id = resolve_project_id(conn, project)
        _flow_project_id, flow_default = require_flow_for_new_run(
            conn, flow, project_id=project_id,
        )
        # If no target_env, resolve from flow's target_env column
        if not target_env:
            if flow_default:
                target_env = flow_default

        # Allocation and insertion share this serialized transaction. The
        # standalone next-id command remains a non-reserving preview.
        run_id = _next_run_id(conn, datetime.now(timezone.utc))

        inserted = conn.execute(
            "INSERT INTO deployment_runs "
            "(id, project_id, flow, target_env, release_lineage, created_by, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (run_id, project_id, flow, target_env or None, release_lineage or None,
             created_by, iso8601_now()),
        ).fetchone()
        if inserted is None:
            raise RuntimeError(
                f"deployment run ID {run_id} was claimed concurrently"
            )
        conn.commit()
        return run_id
    finally:
        conn.close()


def cmd_add_item(run_id: str, item_id: int, db_path: Optional[str] = None) -> str:
    """Add item to run. Returns confirmation message."""
    conn = connect(db_path)
    try:
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
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM deployment_runs WHERE id=%s", (run_id,)
        )
        if not exists:
            return f"Error: deployment run '{run_id}' not found"

        if field == "status":
            if value not in VALID_STATUSES:
                return f"Error: invalid status '{value}'"

            # Cross-field consistency guard for status=succeeded
            if value == "succeeded":
                cur_stage = query_scalar(
                    conn,
                    "SELECT COALESCE(current_stage, '') FROM deployment_runs WHERE id=%s",
                    (run_id,),
                ) or ""

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
                conn.execute(
                    "UPDATE deployment_runs SET status=%s, completed_at=%s WHERE id=%s",
                    (value, iso8601_now(), run_id),
                )
                conn.commit()
                return None

        conn.execute(
            f"UPDATE deployment_runs SET {field}=%s WHERE id=%s",
            (value, run_id),
        )
        conn.commit()
        return None
    finally:
        conn.close()
