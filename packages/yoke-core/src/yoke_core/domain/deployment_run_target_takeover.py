"""Atomically carry existing QA into a containing release on the same target.

Only closed members retain their original delivery ownership. Unfinished
members and their private/shared QA move, and run-level QA moves once.
Requirement and execution identities, state, custody and evidence survive.
Selections, snapshots and plan pins re-derive from live state; only plans
whose rows already ran keep their pin.
Ordinary membership removal remains a separate cancellation operation.
"""

from __future__ import annotations

from yoke_core.domain.frontier_workflow_versions import load_frontier_workflow_versions

from collections.abc import Mapping
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.domain_refusal import DomainRefusal
from yoke_core.domain.schema_common import _column_exists

SUPERSEDED_BY_COLUMN = "superseded_by_run_id"
SUPERSEDES_COLUMN = "supersedes_run_id"
NOT_CONTAINED_CODE = "takeover_candidate_not_contained"


class TakeoverRefused(DomainRefusal, ValueError):
    """An older run waits on this target, and this creation may not take it."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def takeover_available(conn: Any) -> bool:
    """Whether both supersession columns have converged on this database."""
    return all(
        _column_exists(conn, "deployment_runs", column)
        for column in (SUPERSEDED_BY_COLUMN, SUPERSEDES_COLUMN)
    )



def has_shared_gates(stages: list[dict[str, Any]]) -> bool:
    """Run-level QA or approval holds every member until it passes."""
    return any(
        stage.get("step_runner") == "human-approval"
        or (stage.get("step_runner") == "qa" and stage.get("scope") == "run")
        for stage in stages
    )



def _members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    return query_rows(
        conn,
        "SELECT dri.item_id,dri.delivery_intent,i.status,i.workflow_version_id FROM deployment_run_items dri "
        "JOIN items i ON i.id=dri.item_id WHERE dri.run_id=%s ORDER BY dri.item_id",
        (run_id,),
    )


def _moving_members(conn: Any, old: Mapping[str, Any]) -> list[dict]:
    """Every member the older run has not closed; only a closed one stays."""
    versions = load_frontier_workflow_versions(conn)
    return [
        member
        for member in _members(conn, str(old["id"]))
        if member["status"]
        not in versions.runtimes[
            int(member["workflow_version_id"])
        ].all_terminal_stage_ids
    ]


def _delivered_any(conn: Any, old_id: str) -> bool:
    versions = load_frontier_workflow_versions(conn)
    return any(
        member["status"]
        in versions.runtimes[int(member["workflow_version_id"])].terminal_stage_ids
        for member in _members(conn, old_id)
    )


def takeover_will_succeed(conn: Any, old_id: str) -> bool:
    """Project settlement for unlocked preparation; locked takeover rechecks."""
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    row = query_one(conn, "SELECT status FROM deployment_runs WHERE id=%s", (old_id,))
    return (
        row is not None
        and row["status"] == "executing"
        and not has_shared_gates(pinned_stages(conn, old_id))
        and _delivered_any(conn, old_id)
    )


def take_over_waiting_run(
    conn: Any,
    new_run_id: str,
    *,
    session_id: Optional[str] = None,
    actor_id: Optional[int] = None,
    apply: bool = True,
) -> Optional[str]:
    """Take over the run waiting on QA on *new_run_id*'s target.

    Returns the superseded run's id, or ``None`` when no run waits. The caller
    owns the transaction: a refusal rolls back the new run with everything here.
    ``apply=False`` projects membership in the provisional transaction.
    The caller must roll it back; no removal audit or settlement is emitted.
    """
    from yoke_core.domain.deployment_run_qa_transfer import qa_ownership_write

    with qa_ownership_write(conn):
        return _take_over(
            conn, new_run_id, session_id=session_id, actor_id=actor_id, apply=apply
        )


def _take_over(conn, new_run_id, *, session_id, actor_id, apply):
    from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on
    from yoke_core.domain.deployment_run_membership_removals import (
        record_membership_removals,
    )
    from yoke_core.domain.deployment_run_takeover_authority import (
        require_takeover_authority,
    )
    from yoke_core.domain.deployment_run_takeover_read import (
        current_takeover_read,
        read_takeover,
        require_contained,
    )
    from yoke_core.domain.deployment_run_takeover_settlement import (
        succeed_taken_over_run,
    )
    from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
    from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership

    if not takeover_available(conn):
        return None
    new_run = query_one(
        conn,
        "SELECT id,project_id,flow,target_environment_id,release_lineage "
        "FROM deployment_runs WHERE id=%s",
        (new_run_id,),
    )
    if (
        new_run is None
        or new_run["target_environment_id"] is None
        or not str(new_run["release_lineage"] or "").strip()
    ):
        # A run prepared before its commit exists has no candidate to compare;
        # its start meets the older run's occupancy instead.
        return None
    from yoke_core.domain.deployment_run_takeover_eligibility import eligible_predecessor

    old = eligible_predecessor(conn, new_run)
    if old is None:
        return None
    old_id = str(old["id"])
    shared = has_shared_gates(old["stages"])
    # The comparison and the removal's shared groups are read before the
    # older run's lock; under it, a constant re-check repeats only what moved.
    read = read_takeover(conn, new_run, old)
    if apply:
        status, _held = lock_run_with_stable_membership(conn, old_id)
        if status != old["status"]:
            return None
    moving = _moving_members(conn, old)
    if apply:
        require_takeover_authority(conn, old_id, int(new_run["project_id"]), session_id)
        read = current_takeover_read(conn, read, new_run, old)
    require_contained(conn, new_run, old, moving, read.verdict)

    reason = (
        f"taken over by run {new_run_id}, whose candidate contains this run's; "
        "the member's QA continues there"
    )
    ids = [int(member["item_id"]) for member in moving]
    from yoke_core.domain.workflow_delivery_binding_validation import (
        validate_deployment_run_members,
    )

    # Established admission may be reopened, but still needs carried source
    # and a valid workflow pin in the successor.
    validate_deployment_run_members(
        conn, run_id=new_run_id, item_ids=ids, attached=True, frozen=True
    )
    transfer_qa_on(
        conn,
        old_id=old_id,
        new_id=new_run_id,
        moving=set(ids),
    )
    # Selection and snapshot derive from live obligations, as a fresh
    # admission's do; readiness skips carried members until freeze.
    from yoke_core.domain.deployment_member_snapshot_write import read_member_snapshots

    selections, snapshots = read_member_snapshots(
        conn, new_run_id, dict.fromkeys(ids), lock=apply
    )
    conn.execute(
        "INSERT INTO deployment_run_items "
        "(run_id,item_id,added_at,delivery_intent,requirement_selection,requirement_snapshot) "
        "SELECT %s,dri.item_id,dri.added_at,dri.delivery_intent,m.selection,m.snapshot "
        "FROM deployment_run_items dri JOIN unnest(%s::bigint[],%s::text[],%s::text[]) "
        "AS m(item_id,selection,snapshot) ON m.item_id=dri.item_id WHERE dri.run_id=%s "
        "ON CONFLICT (run_id,item_id) DO UPDATE SET "
        "delivery_intent=EXCLUDED.delivery_intent,requirement_selection=EXCLUDED.requirement_selection,"
        "requirement_snapshot=EXCLUDED.requirement_snapshot",
        (new_run_id, ids, [selections[i] for i in ids], [snapshots[i] for i in ids], old_id),
    )
    conn.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=ANY(%s)",
        (old_id, ids),
    )
    if apply:
        record_membership_removals(
            conn,
            old_id,
            ids,
            reason=reason,
            session_id=session_id,
            actor_id=actor_id,
            transferred_to_run_id=new_run_id,
        )
    conn.execute(
        f"UPDATE deployment_runs SET {SUPERSEDED_BY_COLUMN}=%s WHERE id=%s",
        (new_run_id, old_id),
    )
    conn.execute(
        f"UPDATE deployment_runs SET {SUPERSEDES_COLUMN}=%s WHERE id=%s",
        (old_id, new_run_id),
    )
    if not apply:
        return old_id
    if old["status"] == "failed":
        pass  # The failed predecessor keeps its failure evidence and status.
    elif old["status"] == "created" or shared or not _delivered_any(conn, old_id):
        terminalize_run_on(
            conn,
            old_id,
            disposition="cancelled",
            reason=f"superseded by run {new_run_id}; QA ownership transferred",
            actor_id=actor_id,
            session_id=str(session_id or ""),
        )
    else:
        succeed_taken_over_run(conn, old_id, new_run_id, old["stages"])
    if ids:
        from yoke_core.domain.deployment_qa_takeover_notice import (
            notify_moved_member_qa,
        )

        notify_moved_member_qa(
            conn,
            old_id=old_id,
            new_id=new_run_id,
            item_ids=ids,
            stages=old["stages"],
        )
    return old_id


__all__ = [
    "NOT_CONTAINED_CODE",
    "SUPERSEDED_BY_COLUMN",
    "SUPERSEDES_COLUMN",
    "TakeoverRefused",
    "has_shared_gates",
    "take_over_waiting_run",
    "takeover_available",
]
