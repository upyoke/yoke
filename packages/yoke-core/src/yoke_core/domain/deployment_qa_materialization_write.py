"""Apply a prepared QA subject under its run lock, then release the lock."""

from yoke_core.domain.deployment_runs_lock import lock_run


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
        lock_run(conn, str(run_id))
        _require_member_still_attached(conn, run_id, member)
        if not stage_read.projection.holds(conn):
            stage_read = reread()
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
    except Exception:
        if commit:
            conn.rollback()
        raise
