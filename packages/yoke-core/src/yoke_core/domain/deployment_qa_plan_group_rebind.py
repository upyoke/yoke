"""An open plan group follows its owning run's current deployment target.

A group's target is frozen at creation. A release takeover moves the group to
the successor run with that target, and a redeploy issues a newer producer
receipt; either way the frozen target names a build the destination no longer
serves. Once the owning run holds a ready receipt the group's target does not
record, every live case of the group is rebound in place to the owning run's
current target, as member cases are: case ids, ``group_id``, ``plan_id`` and
``starting_run_id`` stay, the previous target is kept in
``rebound_from_target_json``, and a pass that proved the same destination on an
inherited build stays credited. A group is left alone while one of its walks
has begun; a begun walk keeps the target its results prove.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, query_rows, utc_now
from yoke_core.domain.deployment_qa_plan_groups import PlanGroup, run_groups

REBIND_RATIONALE = "A moved plan group follows its owning deployment's current target"


def current_group_target(conn: Any, run: Mapping, group: PlanGroup) -> dict:
    """The target ``group`` runs against now; its stored one while still current."""
    from yoke_core.domain.deployment_qa_execution_target import (
        _frozen_producer_receipt_id,
        _resolve_execution_target,
    )
    from yoke_core.domain.deployment_qa_plan_group_writes import (
        _group_target,
        group_subject_from,
    )
    from yoke_core.domain.deployment_qa_target_reads import _latest_ready_receipt_id

    stored = group.target
    deployment = stored.get("deployment") or {}
    pinned = run["stage"].get("target")
    source = (
        str(pinned.get("source_stage") or "").strip()
        if isinstance(pinned, Mapping)
        else ""
    )
    latest = (
        _latest_ready_receipt_id(conn, run_id=str(run["id"]), source_stage=source)
        if source
        else None
    )
    if latest is None or (
        deployment.get("run_id") == str(run["id"])
        and _frozen_producer_receipt_id(stored) == latest
    ):
        return stored
    subject = group_subject_from(run, group)
    fresh = _resolve_execution_target(
        conn, {**subject, "shared_plan": None, "shared_target": None}
    )
    target = _group_target(fresh, deployment["shared_plan"])
    target["deployment"]["starting_run_id"] = deployment.get(
        "starting_run_id", deployment.get("run_id")
    )
    return target


def _walk_begun(conn: Any, group: PlanGroup) -> bool:
    """Whether a live walk of this group already ran, leased or recorded."""
    from yoke_core.domain.deployment_qa_execution_refreeze import unbegun
    from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND deployment_member_item_id IS NULL "
        f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) AND execution_target_json::jsonb "
        "#>> '{deployment,shared_plan,group_id}'=%s",
        (group.run_id, group.stage, group.group_id),
    )
    return any(
        not unbegun(conn, select_plan_execution(conn, str(row["id"]), lock=False))
        for row in rows
    )


def _rebind_rows(conn: Any, group: PlanGroup, target: dict) -> list[int]:
    from yoke_core.domain.deployment_qa_takeover_identity import inherited_target
    from yoke_core.domain.deployment_qa_target_continuity import same_destination
    from yoke_core.domain.deployment_qa_target_reads import _decode_stored_target
    from yoke_core.domain.qa_execution_environment_target import (
        canonical_target,
        target_digest,
    )
    from yoke_core.domain.qa_latest_execution import latest_executions
    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.qa_requirement_pass_currency import (
        passing_requirements_for_rows,
        recorded_execution_target_digest,
    )

    digest = target_digest(target)
    rows = query_rows(
        conn,
        "SELECT * FROM qa_requirements WHERE id=ANY(%s) "
        "AND superseded_by_requirement_id IS NULL AND retracted_at IS NULL "
        "AND execution_target_json IS NOT NULL "
        "AND execution_target_digest IS DISTINCT FROM %s ORDER BY id",
        (list(group.requirement_ids), digest),
    )
    if not rows:
        return []
    attempts = latest_executions(conn, [int(row["id"]) for row in rows])
    passing = passing_requirements_for_rows(conn, rows, attempts)
    now = instant_parameter(conn, utc_now())
    for row in rows:
        stored = _decode_stored_target(row["execution_target_json"])
        if stored is None or target_digest(stored) != row["execution_target_digest"]:
            raise QaPlanError(
                f"qa_requirement_target_invalid: plan group {group.group_id} "
                f"requirement {row['id']} has invalid stored target evidence; "
                "preserve it and use sanctioned retirement or supersession before "
                "running the group again"
            )
        carried = None
        if (
            int(row["id"]) in passing
            and inherited_target(conn, group.run_id, stored)
            and same_destination(stored, target)
        ):
            carried = recorded_execution_target_digest(
                attempts[int(row["id"])]["raw_result"]
            )
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,"
            "execution_target_digest=%s,rebound_from_target_json=%s,"
            "rebound_from_digest=%s,rebound_at=%s,rebind_rationale=%s WHERE id=%s",
            (
                canonical_target(target),
                digest,
                canonical_target(stored),
                carried,
                now,
                REBIND_RATIONALE,
                int(row["id"]),
            ),
        )
    return [int(row["id"]) for row in rows]


def stale_open_groups(conn: Any, run_id: str, stage_name: str) -> list[tuple]:
    """Each open group of the stage with the target it should hold, when changed."""
    from yoke_core.domain.deployment_qa_stage_contract import _run_stage
    from yoke_core.domain.qa_execution_environment_target import target_digest

    groups = [g for g in run_groups(conn, run_id, stage_name) if g.open]
    if not groups:
        return []
    run = _run_stage(conn, str(run_id), str(stage_name), require_active=False)
    stale = []
    for group in groups:
        target = current_group_target(conn, run, group)
        if target_digest(target) != group.digest:
            stale.append((group, target))
    return stale


def rebind_open_groups(conn: Any, run_id: str, stage_name: str) -> list[int]:
    """Rebind every stale open group whose walks have not begun; the caller locks the run."""
    from yoke_core.domain.db_savepoint import savepoint

    rebound: list[int] = []
    with savepoint(conn, "qa_plan_group_rebind", owns=False):
        for group, target in stale_open_groups(conn, run_id, stage_name):
            if not _walk_begun(conn, group):
                rebound.extend(_rebind_rows(conn, group, target))
    return rebound


def refresh_open_groups(conn: Any, run_id: str, stage_name: str) -> list[int]:
    """Rebind stale groups under a short run lock, committed before a begin reads."""
    if not stale_open_groups(conn, run_id, stage_name):
        return []
    from yoke_core.domain.deployment_runs_lock import lock_run

    lock_run(conn, str(run_id))
    rebound = rebind_open_groups(conn, run_id, stage_name)
    conn.commit()
    return rebound


__all__ = [
    "current_group_target",
    "rebind_open_groups",
    "refresh_open_groups",
    "stale_open_groups",
]
