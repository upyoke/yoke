"""Atomically carry existing QA into a containing release on the same target.

Only closed members retain their original delivery ownership. Unfinished
members and their private/shared QA move, and run-level QA moves once.
Requirement and execution identities, state, custody and evidence survive.
Ordinary membership removal remains a separate cancellation operation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.domain_refusal import DomainRefusal
from yoke_core.domain.schema_common import _column_exists

SUPERSEDED_BY_COLUMN = "superseded_by_run_id"
SUPERSEDES_COLUMN = "supersedes_run_id"
NOT_CONTAINED_CODE = "takeover_candidate_not_contained"

_CLOSED_ITEM_STATUSES = frozenset({"done", "cancelled", "stopped"})
_GATE_RUNNERS = frozenset({"qa", "human-approval"})


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


def _is_qa(stage: Mapping[str, Any]) -> bool:
    return stage.get("step_runner") == "qa" and stage.get("scope") in {"item", "run"}


def has_shared_gates(stages: list[dict[str, Any]]) -> bool:
    """Run-level QA or approval holds every member until it passes."""
    return any(
        stage.get("step_runner") == "human-approval"
        or (stage.get("step_runner") == "qa" and stage.get("scope") == "run")
        for stage in stages
    )


def _waits_only_on_qa(row: Mapping[str, Any], stages: list[dict]) -> bool:
    """Deploy stages are done: the cursor stands on QA, gates follow."""
    names = [str(stage.get("name") or "") for stage in stages]
    current = str(row["current_stage"] or "")
    if row["settling_at"] or current not in names:
        return False
    remaining = stages[names.index(current) :]
    return _is_qa(remaining[0]) and all(
        stage.get("step_runner") in _GATE_RUNNERS
        or (stage == stages[-1] and stage.get("step_runner") == "auto")
        for stage in remaining
    )


def _waiting_run(conn: Any, new_run: Mapping[str, Any]) -> Optional[dict]:
    """The executing run on this flow and target still held by QA."""
    from yoke_core.domain.deploy_target_occupancy import open_qa_lines
    from yoke_core.domain.qa_deployment_run_settlement import failed_qa_owner_sql
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    rows = query_rows(
        conn,
        "SELECT id,status,current_stage,settling_at,release_lineage,supersedes_run_id "
        "FROM deployment_runs "
        "WHERE project_id=%s AND flow=%s AND target_environment_id=%s "
        f"AND (status='executing' OR ({failed_qa_owner_sql(conn, 'deployment_runs')})) "
        "AND superseded_by_run_id IS NULL AND id<>%s ORDER BY id",
        (
            new_run["project_id"],
            new_run["flow"],
            new_run["target_environment_id"],
            new_run["id"],
        ),
    )
    for row in rows:
        stages = pinned_stages(conn, str(row["id"]))
        eligible = (
            row["status"] == "failed" and not row["settling_at"]
        ) or _waits_only_on_qa(row, stages)
        if eligible and open_qa_lines(conn, str(row["id"]), first_wait=True):
            return {**dict(row), "stages": stages}
    return None


def _members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    return query_rows(
        conn,
        "SELECT dri.item_id,dri.delivery_intent,i.status FROM deployment_run_items dri "
        "JOIN items i ON i.id=dri.item_id WHERE dri.run_id=%s ORDER BY dri.item_id",
        (run_id,),
    )


def _moving_members(conn: Any, old: Mapping[str, Any]) -> list[dict]:
    """Every member the older run has not closed; only a closed one stays."""
    return [
        member
        for member in _members(conn, str(old["id"]))
        if member["status"] not in _CLOSED_ITEM_STATUSES
    ]


def _delivered_any(conn: Any, old_id: str) -> bool:
    return any(member["status"] == "done" for member in _members(conn, old_id))


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
    from yoke_core.domain.deployment_run_member_admission import (
        MemberAdmission,
        admit_run_items,
    )
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
    old = _waiting_run(conn, new_run)
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
    # Preserve the original admission snapshots and selection. Admission still
    # validates the successor, but cannot replace the obligations already owed.
    memberships = query_rows(
        conn,
        "SELECT item_id,requirement_selection,requirement_snapshot "
        "FROM deployment_run_items WHERE run_id=%s AND item_id=ANY(%s) ORDER BY item_id",
        (old_id, ids),
    )
    transfer_qa_on(
        conn,
        old_id=old_id,
        new_id=new_run_id,
        moving=set(ids),
        projection=read.projection,
    )
    conn.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=ANY(%s)",
        (old_id, ids),
    )
    admit_run_items(
        conn,
        run_id=new_run_id,
        members=[
            MemberAdmission(int(m["item_id"]), m["delivery_intent"]) for m in moving
        ],
    )
    if memberships:
        conn.execute(
            "UPDATE deployment_run_items m SET requirement_selection=v.selection, "
            "requirement_snapshot=v.snapshot FROM unnest(%s::bigint[],%s::text[],%s::text[]) "
            "AS v(item_id,selection,snapshot) WHERE m.run_id=%s AND m.item_id=v.item_id",
            (
                ids,
                [m["requirement_selection"] for m in memberships],
                [m["requirement_snapshot"] for m in memberships],
                new_run_id,
            ),
        )
    if apply:
        record_membership_removals(
            conn,
            old_id,
            ids,
            reason=reason,
            session_id=session_id,
            actor_id=actor_id,
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
    elif shared or not _delivered_any(conn, old_id):
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
