"""Allocate and insert one deployment run, with its frozen membership.

Creation is a single transaction on purpose. A retry is the same candidate for
the same items, so its membership is part of the row being created rather than
a follow-up write: committing the run first would leave a member-less retry
behind any copy failure, and a member-less item-bound run can never reach its
own completion gate — which is the defect the retry path exists to remove.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.deployment_flow_state import require_flow_for_new_run
from yoke_core.domain.deployment_run_bound_sources import copy_bound_sources
from yoke_core.domain.deployment_run_create_idempotency import existing_run
from yoke_core.domain.deployment_run_insert import insert_run
from yoke_core.domain.deployment_run_retry_membership import copy_frozen_members
from yoke_core.domain.project_identity import resolve_project_id


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
    inherit_members_from: Optional[str] = None,
    allow_pending_pair_merges: bool = False,
) -> str:
    """Create a new deployment run without a caller key. Returns its ID."""
    run_id, _replayed = create_run(
        project,
        flow,
        environment=environment,
        release_lineage=release_lineage,
        created_by=created_by,
        artifact_identity=artifact_identity,
        db_path=db_path,
        inherit_members_from=inherit_members_from,
        allow_pending_pair_merges=allow_pending_pair_merges,
    )
    return run_id


def create_run(
    project: str,
    flow: str,
    environment: Optional[str] = None,
    release_lineage: Optional[str] = None,
    created_by: str = "operator",
    artifact_identity: Optional[str] = None,
    db_path: Optional[str] = None,
    inherit_members_from: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    create_request: Optional[str] = None,
    allow_pending_pair_merges: bool = False,
) -> tuple[str, bool]:
    """Create a new deployment run. Returns ``(run_id, replayed)``.

    ``idempotency_key`` with its canonical ``create_request`` makes the create
    safe to repeat: under the table lock, a run already created with that key
    and request is returned with ``replayed=True`` instead of minting another,
    and the same key with a different request raises
    :class:`~yoke_core.domain.deployment_run_create_idempotency.IdempotencyKeyConflict`.

    ``environment`` (a registered name) overrides the flow's registered
    target; tier and environment otherwise copy from the flow definition.

    ``inherit_members_from`` copies that run's frozen membership onto the new
    run inside this same transaction. A retry is the same candidate for the
    same items, so the two facts are one write: committing the run first would
    leave a member-less retry behind any copy failure, and a member-less
    item-bound retry is precisely what cannot reach its completion gate.
    """
    conn = connect(db_path)
    try:
        if db_backend.connection_is_postgres(conn):
            conn.execute("LOCK TABLE deployment_runs IN SHARE ROW EXCLUSIVE MODE")
        project_id = resolve_project_id(conn, project)
        if idempotency_key:
            existing = existing_run(conn, project_id, idempotency_key, create_request)
            if existing is not None:
                conn.rollback()
                return existing, True
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
            create_idempotency_key=idempotency_key,
            create_request=create_request if idempotency_key else None,
        )
        if inserted is None:
            raise RuntimeError(f"deployment run ID {run_id} was claimed concurrently")
        if inherit_members_from:
            copy_frozen_members(conn, inherit_members_from, run_id)
            # A retry is the same candidate, which includes every project's
            # source commit and not only its own lineage. Re-resolving the
            # bound branches here would let a retry ship a consumer revision
            # the run it retries never carried.
            copy_bound_sources(conn, inherit_members_from, run_id)
        from yoke_core.domain.deployment_runs_validation import (
            cmd_validate_composition,
        )

        # The row and any inherited members are provisional until the same
        # validator used by the explicit command has checked the pinned
        # sources, carried work, member flows, and dependencies. A refusal
        # rolls back the row, so it consumes no run ID.
        valid, message = cmd_validate_composition(
            run_id,
            allow_pending_pair_merges=allow_pending_pair_merges,
            connection=conn,
        )
        if not valid:
            raise ValueError(message)
        conn.commit()
        return run_id, False
    finally:
        conn.close()


__all__ = ["cmd_create_run", "cmd_next_id", "create_run"]
