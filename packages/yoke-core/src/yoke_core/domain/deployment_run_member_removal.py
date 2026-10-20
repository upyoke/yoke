"""Release a run's member to a later candidate without erasing QA history."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.deployment_run_member_removal_read import read_removal
from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removals,
)
from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_read_scope import composition_operation
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings

#: Removal source for a member whose current candidate moved outside the
#: frozen lineage at settlement; its newer work rides a later release.
SETTLEMENT_REMOVED_BY = "settlement"
REPLACED_REASON = "current candidate is not contained in this run's frozen lineage; awaiting a later release"

#: Removal source for a member that left delivery readiness after the run
#: froze and whose current candidate is outside the frozen lineage.
REOPENED_REMOVED_BY = "reopened for rework"
REOPENED_REASON = "left delivery readiness after this run froze and its current candidate is not contained in the frozen lineage; awaiting a later release"


def retract_member_copies(
    conn: Any, run_id: str, *, item_ids: Iterable[int], reason: str
) -> dict[int, list[int]]:
    """Retract every unsettled copy of these members' QA bound to this run.

    A removed member owes this run nothing, whatever its copies' verdict
    history: completion grades each copy's latest attempt, so a copy that
    passed and later failed would otherwise hold the run. A copy the failed
    run already retired is taken over too, so a retry cannot restore it.
    Retraction keeps
    the rows and their qa_runs; standing item plans survive and the next
    release materializes fresh run-bound copies. Returns each member's
    retracted requirement ids.
    """
    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids or not _table_exists(conn, "qa_requirements"):
        return {}
    rows = query_rows(
        conn,
        "SELECT r.id,r.deployment_member_item_id FROM qa_requirements r "
        "WHERE r.deployment_run_id=%s AND r.deployment_member_item_id=ANY(%s) "
        f"AND (NOT {settled_obligation_sql(conn, 'r')} "
        "OR r.retraction_source='deployment_run') ORDER BY r.id",
        (run_id, ids),
    )
    retracted: dict[int, list[int]] = {}
    for row in rows:
        retracted.setdefault(int(row["deployment_member_item_id"]), []).append(
            int(row["id"])
        )
    retract_requirements(
        conn, [int(row["id"]) for row in rows], reason=reason, source="operator"
    )
    return retracted


def remove_members_on(
    conn: Any,
    run_id: str,
    item_ids: Iterable[int],
    *,
    reason: str,
    session_id: str | None = None,
    actor_id: int | None = None,
    removed_by: str = "steering",
    projection: Any = None,
) -> dict[int, str]:
    """Apply the audited removals and retract the members' unsettled run copies.

    Shared-group copies no remaining member attaches are retracted with them.
    Every step is one statement for the whole set, so removing many members
    costs what removing one does; only owners owed a notice get one each.

    Caller owns the locks and transaction. ``projection`` holds the run's
    shared groups read before the caller's run lock (:func:`read_removal`);
    without it they are read here, as one set per fact, after the deletion.
    Retracted copies keep their verdict history; standing item plans survive
    and the next release materializes fresh run-bound copies. Returns each
    removed member's public ref.
    """
    from yoke_core.domain.deployment_member_removal_notice import notify_removed_member
    from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
        withdraw_deployment_qa_wait_wakes,
    )
    from yoke_core.domain.qa_deployment_member_removal import (
        abort_removed_member_executions,
        retract_orphaned_shared_copies,
    )

    ids = sorted({int(item_id) for item_id in item_ids})
    if not ids:
        return {}
    ref = render_item_ref_lookup(conn, ids)
    deleted = {
        int(row["item_id"])
        for row in conn.execute(
            "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=ANY(%s) "
            "RETURNING item_id",
            (run_id, ids),
        ).fetchall()
    }
    if missing := [item_id for item_id in ids if item_id not in deleted]:
        raise LookupError(
            f"{ref(missing[0])} is not a member of deployment run '{run_id}'; read `yoke deployment-runs get {run_id}` for its members"
        )
    removed_at = record_membership_removals(
        conn, run_id, ids, reason=reason, session_id=session_id, actor_id=actor_id
    )
    gone = ids
    if projection is not None:
        # Every member the projection saw that no longer belongs, including
        # an earlier batch removed in this same transaction.
        remaining = {
            int(row["item_id"])
            for row in conn.execute(
                "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
            ).fetchall()
        }
        gone = sorted({int(row["item_id"]) for row in projection.members()} - remaining)
    stopped, cleaning = abort_removed_member_executions(
        conn, run_id=run_id, item_ids=ids, projection=projection, removed=gone
    )
    cancelled = retract_member_copies(conn, run_id, item_ids=ids, reason=reason)
    retract_orphaned_shared_copies(
        conn, run_id=run_id, reason=reason, projection=projection, removed=gone
    )
    withdraw_deployment_qa_wait_wakes(
        conn, run_id=run_id, item_ids=ids, reason="member_removed"
    )
    for item_id in ids:
        notify_removed_member(
            conn,
            run_id=run_id,
            item_id=item_id,
            public_ref=ref(item_id),
            reason=reason,
            removed_by=removed_by,
            removed_at=removed_at,
            execution_aborted=item_id in stopped,
            host_cleanup_pending=item_id in cleaning,
            cancelled_requirement_ids=cancelled.get(item_id, ()),
        )
    return {item_id: ref(item_id) for item_id in ids}


def remove_member_on(
    conn: Any,
    run_id: str,
    item_id: int,
    *,
    reason: str,
    session_id: str | None = None,
    actor_id: int | None = None,
    removed_by: str = "steering",
    projection: Any = None,
) -> str:
    """Remove one member; see :func:`remove_members_on`."""
    return remove_members_on(
        conn,
        run_id,
        (int(item_id),),
        reason=reason,
        session_id=session_id,
        actor_id=actor_id,
        removed_by=removed_by,
        projection=projection,
    )[int(item_id)]


@composition_operation
def cmd_remove_item(
    run_id: str,
    item_id: int,
    *,
    reason: str,
    session_id: str | None = None,
    actor_id: int | None = None,
    db_path: str | None = None,
) -> str:
    """Remove a created member or one owing executing/failed independent item QA.

    The guard and the run's shared groups are read before the run row lock;
    the lock covers the fingerprint check and the removal's writes.
    """
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError(
            "a membership removal needs --reason naming why this run must not deliver the item; it is recorded on the run for audit"
        )
    conn = connect(db_path)
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        read = read_removal(conn, run_id=run_id, item_ids=(int(item_id),))
        lock_run(conn, run_id)
        if not read.projection.holds(conn):
            read = read_removal(conn, run_id=run_id, item_ids=(int(item_id),))
        if read.refusal is not None:
            raise read.refusal
        status = read.status
        ref = remove_member_on(
            conn,
            run_id,
            int(item_id),
            reason=reason,
            session_id=session_id,
            actor_id=actor_id,
            projection=read.projection,
        )
        conn.commit()
        recovery = f"Re-attach while created with `yoke deployment-runs add-item {run_id} {ref}`."
        if status == "failed":
            recovery = (
                f"Resume this same run with `yoke watch deploy -- {run_id} "
                "--from-stage item-qa`."
            )
        elif status == "executing":
            from yoke_core.domain.deployment_run_auto_completion import (
                continue_after_settlement,
            )

            result = continue_after_settlement(conn, run_id)
            if not result.completed:
                from yoke_core.domain.deployment_run_driver_notice import (
                    push_run_scoped_notice,
                )

                project = query_one(
                    conn,
                    "SELECT project_id FROM deployment_runs WHERE id=%s",
                    (run_id,),
                )
                delivery = push_run_scoped_notice(
                    conn,
                    run_id=run_id,
                    project_id=int(project["project_id"]),
                    body_for_route=lambda _route: (
                        f"Removed {ref} from run {run_id}: {reason}. "
                        "Re-evaluate its remaining item QA and continue this same run "
                        f"with `yoke watch deploy -- {run_id}`."
                    ),
                    idempotency_key=f"deployment-member-removal:{run_id}:{item_id}",
                )
                conn.commit()
                if not delivery:
                    print(
                        f"Run {run_id} removal is durable but no driver received continuation; re-drive it with `yoke watch deploy -- {run_id}`."
                    )
            recovery = (
                result.failure
                or result.waiting
                or "The run finished with its remaining members."
            )
        return (
            f"Removed {ref} from run {run_id} ({reason}). Composition will not "
            "re-enroll it; its landed code still ships with this candidate and "
            f"a later release enrolls it. {recovery}"
        )
    finally:
        conn.close()
