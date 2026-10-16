"""Validate a run being created, first without the creation lock, then under it.

Composition resolves bound branches and walks commit ranges on the repository
host, which takes seconds to minutes. Creation serializes on a global lock, so
those reads ran once per create while every concurrent create waited. Now the
same validator runs twice inside one read scope: once before the lock on a
provisional row that is rolled back, and once under the lock on the real row.
The locked pass reuses the branch heads and comparisons the first pass
resolved and re-checks only database facts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_flow_state import require_flow_for_new_run
from yoke_core.domain.deployment_run_bound_sources import copy_bound_sources
from yoke_core.domain import deployment_run_create_idempotency as idempotency
from yoke_core.domain.deployment_run_insert import insert_run
from yoke_core.domain.deployment_run_retry_membership import copy_frozen_members
from yoke_core.domain.project_identity import resolve_project_id

#: Prefix of the provisional id the unlocked pass validates under. The
#: allocator only issues ``run-YYYYMMDD-NNN``, so this row never collides with
#: (or waits on) a run another create is inserting.
UNLOCKED_RUN_PREFIX = "run-unlocked-"


def refuse_run_that_cannot_execute(
    conn: Any, flow: str, release_lineage: Optional[str]
) -> None:
    """Apply the dispatch stage's lineage requirement at creation time."""
    from yoke_core.domain import deployment_run_lineage_requirement as lineage
    from yoke_core.domain.json_helper import loads_text

    row = conn.execute(
        "SELECT stages FROM deployment_flows WHERE id = %s", (flow,)
    ).fetchone()
    stages = loads_text(row[0]) if row and row[0] else []
    lineage.require_lineage_for_stages(stages, release_lineage, flow=flow)


def run_target(
    conn: Any, flow: str, project_id: int, environment: Optional[str]
) -> tuple[Optional[str], Optional[int]]:
    """The flow's registered tier and environment, or the named override."""
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
    return target_tier, target_environment_id


def compose_run(
    conn: Any,
    run_id: str,
    *,
    created_at: datetime,
    project_id: int,
    target: tuple[Optional[str], Optional[int]],
    flow: str,
    release_lineage: Optional[str],
    created_by: str,
    artifact_identity: Optional[str],
    inherit_members_from: Optional[str],
    allow_pending_pair_merges: bool,
    create_idempotency_key: Optional[str] = None,
    create_request: Optional[str] = None,
    session_id: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> tuple[bool, str]:
    """Insert the run row, take over a run waiting on item QA on its target,
    copy a retry's membership, and validate composition."""
    from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run
    from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
    from yoke_core.domain.deployment_start_timing import timed_preparation

    inserted = insert_run(
        conn,
        run_id=run_id,
        project_id=project_id,
        flow=flow,
        target_tier=target[0],
        target_environment_id=target[1],
        release_lineage=release_lineage,
        created_by=created_by,
        created_at=created_at,
        artifact_identity=artifact_identity,
        create_idempotency_key=create_idempotency_key,
        create_request=create_request,
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
    timed_preparation(
        "create_takeover",
        take_over_waiting_run,
        conn,
        run_id,
        session_id=session_id,
        actor_id=actor_id,
        apply=not run_id.startswith(UNLOCKED_RUN_PREFIX),
    )
    # The row and any inherited members are provisional until the same
    # validator used by the explicit command has checked the pinned
    # sources, carried work, member flows, and dependencies. A refusal
    # rolls back the row, so it consumes no run ID.
    return timed_preparation(
        "create_validation",
        cmd_validate_composition,
        run_id,
        allow_pending_pair_merges=allow_pending_pair_merges,
        connection=conn,
        # Itemless creation precedes add-item; start checks the count.
        require_item_qa_members=False,
    )


def validate_before_lock(
    conn: Any,
    project: str,
    *,
    environment: Optional[str],
    idempotency_key: Optional[str],
    create_request: Optional[str],
    **run: Any,
) -> None:
    """Pay composition's repository reads before the creation lock is taken.

    Validates a provisional row under :data:`UNLOCKED_RUN_PREFIX`, then rolls
    the transaction back: the row, members, recorded sources and enrollment
    are gone and this verdict decides nothing. What remains is the caller's
    read scope. A comparison whose basis moved before the lock, such as a
    newer preceding release, has a different key and is derived again under
    the lock rather than reused.

    A keyed repeat of a run that already exists skips the reads, because the
    locked pass replays it. Any failure here is left to the locked pass,
    which repeats each step and refuses under the run's real id.
    """
    try:
        project_id = resolve_project_id(conn, project)
        if idempotency_key and idempotency.existing_run(
            conn, project_id, idempotency_key, create_request
        ):
            return
        target = run_target(conn, run["flow"], project_id, environment)
        refuse_run_that_cannot_execute(conn, run["flow"], run["release_lineage"])
        compose_run(
            conn,
            f"{UNLOCKED_RUN_PREFIX}{uuid4().hex}",
            created_at=utc_now(),
            project_id=project_id,
            target=target,
            **run,
        )
    except Exception:  # noqa: BLE001 - the locked pass refuses it by name
        pass
    finally:
        conn.rollback()


__all__ = [
    "UNLOCKED_RUN_PREFIX",
    "compose_run",
    "refuse_run_that_cannot_execute",
    "run_target",
    "validate_before_lock",
]
