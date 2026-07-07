"""Preview-environment lifecycle for deployment runs.

Owns the full claim/release flow:

- ``cmd_preview_check`` — read-only occupancy probe (returns status string).
- ``cmd_preview_claim`` — minimal upsert claim, no event emission.
- ``cmd_preview_release`` — release on run completion, emits ``PreviewEnvCleaned``.
- ``cmd_check_preview_occupancy`` — structured occupancy + age + item-list output.
- ``cmd_claim_preview`` — full claim path with overwrite detection and event emission.
- ``cmd_can_cleanup_preview`` — gate for adhoc cleanup based on lineage final-target run status.
- ``cmd_resolve_target_env`` — resolve target env from override or flow default.

Also holds ``_emit_event`` as a private helper — the only callers post-split
are the two preview claim/release paths in this module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.db_helpers import connect, iso8601_now, query_one, query_rows, query_scalar
from yoke_core.domain.deployment_runs_schema import VALID_ENV_TYPES
from yoke_core.domain.project_identity import ProjectIdentity, resolve_project
from yoke_core.domain.time_parse import age_minutes_since


def _project_identity(conn: Any, project: str) -> ProjectIdentity:
    ident = resolve_project(conn, project)
    assert ident is not None
    return ident


# ---------------------------------------------------------------------------
# Event helper (best-effort)
# ---------------------------------------------------------------------------

def _emit_event(
    name: str,
    kind: str = "lifecycle",
    event_type: str = "preview_env",
    source_type: str = "script",
    outcome: str = "completed",
    project: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort event emission via the native Python emitter."""
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        kwargs: Dict[str, Any] = {
            "event_kind": kind,
            "event_type": event_type,
            "source_type": source_type,
            "outcome": outcome,
        }
        if project:
            kwargs["project"] = project
        if context is not None:
            kwargs["context"] = context
        _native_emit(name, **kwargs)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Target env resolution
# ---------------------------------------------------------------------------

def cmd_resolve_target_env(
    project: str,
    flow: str,
    target_env_override: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Resolve target env from flow default or override."""
    if target_env_override:
        return target_env_override

    conn = connect(db_path)
    try:
        ident = _project_identity(conn, project)
        flow_target = query_scalar(
            conn,
            "SELECT COALESCE(target_env, '') FROM deployment_flows "
            "WHERE id=%s AND project_id=%s",
            (flow, ident.id),
        )
        return flow_target if flow_target else ""
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Preview occupancy + simple claim/release
# ---------------------------------------------------------------------------

def cmd_preview_check(
    project: str,
    env_name: str,
    db_path: Optional[str] = None,
) -> str:
    """Return occupancy status of a preview environment."""
    conn = connect(db_path)
    try:
        ident = _project_identity(conn, project)
        row = query_one(
            conn,
            "SELECT pe.id, p.slug AS project, pe.env_name, COALESCE(pe.run_id,''), "
            "pe.status, COALESCE(pe.url,''), pe.created_at "
            "FROM deployment_preview_environments pe "
            "JOIN projects p ON p.id = pe.project_id "
            "WHERE pe.project_id=%s AND pe.env_name=%s",
            (ident.id, env_name),
        )
        if row is None:
            return "available"
        return str(row[4])  # status column
    finally:
        conn.close()


def cmd_preview_claim(
    run_id: str,
    project: str,
    env_name: str,
    db_path: Optional[str] = None,
) -> str:
    """Claim preview environment for run. Returns confirmation message."""
    conn = connect(db_path)
    try:
        ident = _project_identity(conn, project)
        conn.execute(
            "INSERT INTO deployment_preview_environments "
            "(project_id, env_name, run_id, status, created_at) "
            "VALUES (%s, %s, %s, 'claimed', %s) "
            "ON CONFLICT(project_id, env_name) DO UPDATE SET run_id=%s, status='claimed'",
            (ident.id, env_name, run_id, iso8601_now(), run_id),
        )
        conn.commit()
        return f"Claimed preview '{env_name}' for run {run_id}"
    finally:
        conn.close()


def cmd_preview_release(run_id: str, db_path: Optional[str] = None) -> str:
    """Release preview environment after run. Returns confirmation message."""
    conn = connect(db_path)
    try:
        # Get preview env details before release (for event)
        prev_row = query_one(
            conn,
            "SELECT pe.env_name, p.slug AS project, pe.env_type "
            "FROM deployment_preview_environments pe "
            "JOIN projects p ON p.id = pe.project_id "
            "WHERE pe.run_id=%s",
            (run_id,),
        )

        conn.execute(
            "UPDATE deployment_preview_environments SET run_id=NULL, status='available' WHERE run_id=%s",
            (run_id,),
        )
        conn.commit()

        # Emit cleanup event if we had a preview
        if prev_row:
            _emit_event(
                name="PreviewEnvCleaned",
                project=str(prev_row[1]),
                context={
                    "run_id": run_id,
                    "env_name": str(prev_row[0]),
                    "env_type": str(prev_row[2]),
                },
            )

        return f"Released preview environments for run {run_id}"
    finally:
        conn.close()


def cmd_check_preview_occupancy(
    project: str,
    env_name: str,
    db_path: Optional[str] = None,
) -> str:
    """Structured occupancy check.

    Returns: "empty" or "active|{run-id}|{item-list}|{age-minutes}" or
    "stale|{run-id}|{item-list}|{age-minutes}".
    """
    conn = connect(db_path)
    try:
        ident = _project_identity(conn, project)
        row = query_one(
            conn,
            "SELECT pe.run_id, pe.status, pe.created_at "
            "FROM deployment_preview_environments pe "
            "WHERE pe.project_id=%s AND pe.env_name=%s",
            (ident.id, env_name),
        )

        if row is None:
            return "empty"

        run_id = row[0]
        status = row[1]
        age = age_minutes_since(row[2])

        if status == "available" or not run_id:
            return "empty"

        # Get items enrolled in the occupying run
        items_rows = query_rows(
            conn,
            "SELECT 'YOK-' || item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id ASC",
            (run_id,),
        )
        if items_rows:
            item_list = ",".join(str(r[0]) for r in items_rows)
        else:
            item_list = "none"

        # Map DB status to interface contract token: claimed -> active
        out_status = "active" if status == "claimed" else status

        return f"{out_status}|{run_id}|{item_list}|{age}"
    finally:
        conn.close()


def cmd_claim_preview(
    run_id: str,
    project: str,
    env_name: str,
    env_type: str = "adhoc",
    db_path: Optional[str] = None,
) -> str:
    """Claim preview env for run with event emission. Returns confirmation message."""
    if env_type not in VALID_ENV_TYPES:
        raise ValueError(f"env-type must be 'shared' or 'adhoc'")

    conn = connect(db_path)
    try:
        ident = _project_identity(conn, project)
        # Check if already occupied (for event type decision)
        existing_run = query_scalar(
            conn,
            "SELECT COALESCE(run_id, '') FROM deployment_preview_environments "
            "WHERE project_id=%s AND env_name=%s AND status='claimed'",
            (ident.id, env_name),
        )
        is_overwrite = bool(existing_run and existing_run != run_id)

        # Upsert
        conn.execute(
            "INSERT INTO deployment_preview_environments "
            "(project_id, env_name, run_id, status, env_type, created_at) "
            "VALUES (%s, %s, %s, 'claimed', %s, %s) "
            "ON CONFLICT(project_id, env_name) DO UPDATE SET run_id=%s, status='claimed', env_type=%s",
            (ident.id, env_name, run_id, env_type, iso8601_now(), run_id, env_type),
        )
        conn.commit()

        # Emit event
        event_name = "PreviewEnvOverwritten" if is_overwrite else "PreviewEnvCreated"
        _emit_event(
            name=event_name,
            project=ident.slug,
            context={
                "run_id": run_id,
                "env_name": env_name,
                "env_type": env_type,
                "previous_run": existing_run or "",
            },
        )

        if is_overwrite:
            return f"Overwritten preview '{env_name}' for run {run_id} (was: {existing_run})"
        return f"Claimed preview '{env_name}' for run {run_id}"
    finally:
        conn.close()


def cmd_can_cleanup_preview(run_id: str, db_path: Optional[str] = None) -> Tuple[bool, str]:
    """Check if a run's preview can be cleaned up.

    Returns (allowed, message).
    Rules:
      - shared/persistent envs: never auto-cleanable
      - adhoc envs: only if final-target run in lineage succeeded
      - no lineage or no final-target run: blocked
    """
    conn = connect(db_path)
    try:
        preview_row = query_one(
            conn,
            "SELECT pe.env_type, pe.env_name, p.slug AS project "
            "FROM deployment_preview_environments pe "
            "JOIN projects p ON p.id = pe.project_id "
            "WHERE pe.run_id=%s",
            (run_id,),
        )
        if preview_row is None:
            return False, f"No preview environment for run {run_id}"

        env_type = preview_row[0]
        env_name = preview_row[1]

        if env_type == "shared":
            return False, f"blocked: shared preview '{env_name}' is never auto-cleanable"

        lineage = query_scalar(
            conn,
            "SELECT COALESCE(release_lineage, '') FROM deployment_runs WHERE id=%s",
            (run_id,),
        )
        if not lineage:
            return False, f"blocked: no release lineage for run {run_id}"

        final_run_status = query_scalar(
            conn,
            "SELECT status FROM deployment_runs "
            "WHERE release_lineage=%s AND id <> %s "
            "ORDER BY created_at DESC LIMIT 1",
            (lineage, run_id),
        )

        if not final_run_status:
            return False, f"blocked: no final-target run in lineage '{lineage}'"

        if final_run_status == "succeeded":
            return True, "allowed: final-target run succeeded"

        return False, f"blocked: final-target run status is '{final_run_status}'"
    finally:
        conn.close()
