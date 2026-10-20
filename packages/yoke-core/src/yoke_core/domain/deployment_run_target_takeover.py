"""A new run takes over an older run on its target that only waits on item QA.

A run occupies its target until its QA settles
(:mod:`yoke_core.domain.deploy_target_occupancy`). Once its deploy stages are
done, the only thing still holding the target is item QA — which can be slow,
and which a newer candidate that contains this one can answer just as well.

So creating a run for the same flow and target takes the older run over,
inside the creation transaction, and settles it there too: the older run is
never left executing without a driver.

* **No run-level QA or approval in the flow.** Only a member the older run
  already closed stays: its own passed item QA closed it there. Every
  unclosed member — waiting, passed but not closed, carried without final
  intent — moves through the audited removal path into the new run. The
  older run then reads succeeded when it delivered at least one member
  (:mod:`~yoke_core.domain.deployment_run_takeover_settlement`), and is
  cancelled otherwise.
* **Run-level QA or approval in the flow.** The shared gates hold every
  member, so every unclosed member moves and the older run is cancelled as
  superseded. Nothing is recorded as passed, and no approval is skipped; the
  new run seeds its run-level QA from the flow definition, so the gates keep
  their order.

Either way no memberless obligation stays open on the older run: shared-plan
copies and run-level requirements without a pass are retracted, and the new
run materializes its own when its members still attach those plans. The
takeover is refused, naming the members to release by hand, unless the new
candidate contains the older one, and refused unless the creating session may
take the older run over
(:mod:`~yoke_core.domain.deployment_run_takeover_authority`). Both runs record
which superseded which.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.domain_refusal import DomainRefusal
from yoke_core.domain.schema_common import _column_exists

SUPERSEDED_BY_COLUMN = "superseded_by_run_id"
SUPERSEDES_COLUMN = "supersedes_run_id"
TAKEOVER_REMOVED_BY = "run takeover"
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


def _is_item_qa(stage: Mapping[str, Any]) -> bool:
    return stage.get("step_runner") == "qa" and stage.get("scope") == "item"


def has_shared_gates(stages: list[dict[str, Any]]) -> bool:
    """Run-level QA or approval holds every member until it passes."""
    return any(
        stage.get("step_runner") == "human-approval"
        or (stage.get("step_runner") == "qa" and stage.get("scope") == "run")
        for stage in stages
    )


def _waits_only_on_item_qa(row: Mapping[str, Any], stages: list[dict]) -> bool:
    """Deploy stages are done: the cursor stands on item QA, gates follow."""
    names = [str(stage.get("name") or "") for stage in stages]
    current = str(row["current_stage"] or "")
    if row["settling_at"] or current not in names:
        return False
    remaining = stages[names.index(current) :]
    return _is_item_qa(remaining[0]) and all(
        stage.get("step_runner") in _GATE_RUNNERS
        or (stage == stages[-1] and stage.get("step_runner") == "auto")
        for stage in remaining
    )


def _waiting_run(conn: Any, new_run: Mapping[str, Any]) -> Optional[dict]:
    """The executing run on this flow and target still held by item QA."""
    from yoke_core.domain.deploy_target_occupancy import open_qa_lines
    from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages

    rows = query_rows(
        conn,
        "SELECT id,current_stage,settling_at,release_lineage FROM deployment_runs "
        "WHERE project_id=%s AND flow=%s AND target_environment_id=%s "
        "AND status='executing' AND id<>%s ORDER BY id",
        (
            new_run["project_id"],
            new_run["flow"],
            new_run["target_environment_id"],
            new_run["id"],
        ),
    )
    for row in rows:
        stages = pinned_stages(conn, str(row["id"]))
        if _waits_only_on_item_qa(row, stages) and open_qa_lines(
            conn, str(row["id"]), first_wait=True
        ):
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

    return not has_shared_gates(pinned_stages(conn, old_id)) and _delivered_any(
        conn, old_id
    )


def _retract_memberless(conn: Any, old_id: str, reason: str) -> None:
    """Retract shared-plan copies and run-level requirements nobody passed."""
    from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
    from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
    from yoke_core.domain.qa_plan_attachment_retract import retract_requirements

    rows = query_rows(
        conn,
        "SELECT r.id FROM qa_requirements r WHERE r.deployment_run_id=%s "
        "AND r.deployment_member_item_id IS NULL "
        f"AND NOT {settled_obligation_sql(conn, 'r')} "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr "
        f"WHERE qr.id=({latest_execution_id_sql('r.id')}) AND qr.verdict='pass')",
        (old_id,),
    )
    retract_requirements(
        conn, [int(row["id"]) for row in rows], reason=reason, source="deployment_run"
    )


def take_over_waiting_run(
    conn: Any,
    new_run_id: str,
    *,
    session_id: Optional[str] = None,
    actor_id: Optional[int] = None,
    apply: bool = True,
) -> Optional[str]:
    """Take over the run waiting on item QA on *new_run_id*'s target.

    Returns the superseded run's id, or ``None`` when no run waits. The caller
    owns the transaction: a refusal rolls back the new run with everything here.
    ``apply=False`` projects membership in the provisional transaction.
    The caller must roll it back; no removal audit or settlement is emitted.
    """
    from yoke_core.domain.deployment_run_member_admission import (
        MemberAdmission,
        admit_run_items,
    )
    from yoke_core.domain.deployment_run_member_removal import remove_members_on
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
    if not apply:
        moving = _moving_members(conn, old)
        require_contained(conn, new_run, old, moving)
        conn.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=ANY(%s)",
            (old_id, [int(member["item_id"]) for member in moving]),
        )
        admit_run_items(
            conn,
            run_id=new_run_id,
            members=[
                MemberAdmission(int(m["item_id"]), m["delivery_intent"]) for m in moving
            ],
        )
        return old_id
    # The comparison and the removal's shared groups are read before the
    # older run's lock; under it, a constant re-check repeats only what moved.
    read = read_takeover(conn, new_run, old)
    status, _held = lock_run_with_stable_membership(conn, old_id)
    if status != "executing":
        return None
    moving = _moving_members(conn, old)
    require_takeover_authority(conn, old_id, int(new_run["project_id"]), session_id)
    read = current_takeover_read(conn, read, new_run, old)
    require_contained(conn, new_run, old, moving, read.verdict)

    reason = (
        f"taken over by run {new_run_id}, whose candidate contains this run's; "
        "the member's QA continues there"
    )
    remove_members_on(
        conn,
        old_id,
        [int(member["item_id"]) for member in moving],
        reason=reason,
        session_id=session_id,
        actor_id=actor_id,
        removed_by=TAKEOVER_REMOVED_BY,
        projection=read.projection,
    )
    admit_run_items(
        conn,
        run_id=new_run_id,
        members=[
            MemberAdmission(int(member["item_id"]), member["delivery_intent"])
            for member in moving
        ],
    )
    if shared or not _delivered_any(conn, old_id):
        terminalize_run_on(
            conn,
            old_id,
            disposition="cancelled",
            reason=f"superseded by run {new_run_id}; nothing here was passed",
            actor_id=actor_id,
            session_id=str(session_id or ""),
        )
    else:
        _retract_memberless(conn, old_id, reason)
        succeed_taken_over_run(conn, old_id, new_run_id, old["stages"])
    conn.execute(
        f"UPDATE deployment_runs SET {SUPERSEDED_BY_COLUMN}=%s WHERE id=%s",
        (new_run_id, old_id),
    )
    conn.execute(
        f"UPDATE deployment_runs SET {SUPERSEDES_COLUMN}=%s WHERE id=%s",
        (old_id, new_run_id),
    )
    return old_id


__all__ = [
    "NOT_CONTAINED_CODE",
    "SUPERSEDED_BY_COLUMN",
    "SUPERSEDES_COLUMN",
    "TAKEOVER_REMOVED_BY",
    "TakeoverRefused",
    "has_shared_gates",
    "take_over_waiting_run",
    "takeover_available",
]
