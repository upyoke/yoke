"""Apply a prepared QA subject under its run lock, then release the lock.

The read stays outside the lock: a run that changed since it is read again
unlocked (:func:`lock_current_read`), so no run-wide query, git or HTTP call
ever runs while this writer holds the run row.
"""

from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error
from yoke_core.domain.deployment_runs_lock import lock_current_read


def write_prepared_stage(
    conn,
    stage_read,
    *,
    reread,
    run_id,
    member,
    commit=True,
    replaced_requirement_ids=frozenset(),
    advance_projection=False,
):
    from yoke_core.domain.deployment_qa_stage_materialization import (
        _require_member_still_attached,
    )
    from yoke_core.domain.deployment_qa_shared_duplicates import retire_member_copies
    from yoke_core.domain.deployment_qa_snapshot_selection import freeze_selected_plans
    from yoke_core.domain.deployment_qa_subject_materialization import (
        materialize_subject,
    )

    try:
        stage_read = lock_current_read(
            conn,
            str(run_id),
            reread,
            prepared=stage_read,
            holds=lambda current: current.projection.holds(conn),
        )
        _require_member_still_attached(conn, run_id, member)
        subject, target = stage_read.subject, stage_read.target
        freeze_selected_plans(conn, subject, stage_read.snapshots)

        def write(group, group_target, admitted, snapshots):
            return materialize_subject(
                conn,
                subject=group,
                target=group_target,
                admitted=admitted,
                snapshots=snapshots,
                commit=False,
                replaced_requirement_ids=replaced_requirement_ids,
            )

        if not stage_read.shared:
            result = materialize_subject(
                conn,
                subject=subject,
                target=target,
                admitted=stage_read.admitted,
                snapshots=stage_read.snapshots,
                commit=False,
                replaced_requirement_ids=replaced_requirement_ids,
                withdrawn_discharge=stage_read.withdrawn_discharge,
            )
        else:
            results = []
            for snapshot, group, group_target, members in stage_read.shared:
                results.append(write(group, group_target, [], [snapshot]))
                retire_member_copies(
                    conn,
                    group,
                    group_target,
                    [
                        *results[-1]["created_requirement_ids"],
                        *results[-1]["existing_requirement_ids"],
                    ],
                    members=members,
                )
            for group, group_target, snapshot in stage_read.corrections:
                results.append(write(group, group_target, [], [snapshot]))
            if stage_read.private or stage_read.private_snapshots:
                results.append(
                    write(
                        subject,
                        target,
                        stage_read.private,
                        stage_read.private_snapshots,
                    )
                )
            result = {
                **results[0],
                "deployment_member_item_id": member,
                "created_requirement_ids": [
                    r for part in results for r in part["created_requirement_ids"]
                ],
                "existing_requirement_ids": [
                    r for part in results for r in part["existing_requirement_ids"]
                ],
            }
        if advance_projection:
            from yoke_core.domain.deployment_run_qa_fingerprint import (
                run_qa_fingerprint,
            )

            stage_read.projection.fingerprint = run_qa_fingerprint(conn, str(run_id))
        if commit:
            conn.commit()
        return result
    except Exception as exc:
        if commit:
            rollback_after_error(conn, exc)
        raise
