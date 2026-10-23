"""Apply prepared QA subjects under their run lock, then release the lock.

The read stays outside the lock: a run that changed since it is read again
unlocked (:func:`lock_current_read`), so no run-wide query, git or HTTP call
ever runs while this writer holds the run row. A dispatch writes its whole
cohort under one lock and one fingerprint check, because every member's
read shares one projection of the run.
"""

from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error
from yoke_core.domain.deployment_runs_lock import (
    lock_current_read,
    run_lock_held,
    run_lock_is_held,
)

_MEMBER_WRITE_SAVEPOINT = "yoke_member_qa_write"


def _write_subject(conn, stage_read, *, member, replaced_requirement_ids):
    from yoke_core.domain.deployment_qa_shared_duplicates import retire_member_copies
    from yoke_core.domain.deployment_qa_snapshot_selection import freeze_selected_plans
    from yoke_core.domain.deployment_qa_subject_materialization import (
        materialize_subject,
    )

    if stage_read.selected_admission is not None:
        return stage_read.selected_admission
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
        return materialize_subject(
            conn,
            subject=subject,
            target=target,
            admitted=stage_read.admitted,
            snapshots=stage_read.snapshots,
            commit=False,
            replaced_requirement_ids=replaced_requirement_ids,
            withdrawn_discharge=stage_read.withdrawn_discharge,
        )
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
            write(subject, target, stage_read.private, stage_read.private_snapshots)
        )
    return {
        **results[0],
        "deployment_member_item_id": member,
        "created_requirement_ids": [
            r for part in results for r in part["created_requirement_ids"]
        ],
        "existing_requirement_ids": [
            r for part in results for r in part["existing_requirement_ids"]
        ],
    }


def write_prepared_stage(
    conn,
    stage_read,
    *,
    reread,
    run_id,
    member,
    commit=True,
    replaced_requirement_ids=frozenset(),
):
    from yoke_core.domain.deployment_qa_stage_materialization import (
        _require_member_still_attached,
    )

    def read_attached():
        # A removal changes the run, so the re-read names it before the
        # subject read refuses the missing member less precisely.
        _require_member_still_attached(conn, run_id, member)
        return reread()

    try:
        # Inside a cohort write the cohort's one check already proved this
        # read current under the lock this transaction holds.
        if not run_lock_is_held(conn, str(run_id)):
            stage_read = lock_current_read(
                conn,
                str(run_id),
                read_attached,
                prepared=stage_read,
                holds=lambda current: current.projection.holds(conn),
            )
        _require_member_still_attached(conn, run_id, member)
        result = _write_subject(
            conn,
            stage_read,
            member=member,
            replaced_requirement_ids=replaced_requirement_ids,
        )
        if commit:
            conn.commit()
        return result
    except Exception as exc:
        if commit:
            rollback_after_error(conn, exc)
        raise


def write_prepared_cohort(conn, *, run_id, read, write):
    """Write every member ``read()`` prepared under one run lock; return errors.

    ``read()`` answers ``(reads, errors)`` for the cohort, unlocked. One
    fingerprint check proves every read current; ``write(member, read)``
    then runs per member with the run's re-locks answered from the held
    lock. A member whose write refuses rolls back only its own savepoint,
    and the cohort commits once.
    """
    from yoke_core.domain.deployment_qa_stage_materialization import (
        removed_member_refusals,
    )

    prepared = read()
    if not prepared[0]:
        return dict(prepared[1])

    def holds(current):
        reads = current[0]
        return not reads or next(iter(reads.values())).projection.holds(conn)

    try:
        reads, errors = lock_current_read(
            conn, str(run_id), read, prepared=prepared, holds=holds
        )
        errors = {**errors, **removed_member_refusals(conn, run_id, reads)}
        with run_lock_held(conn, str(run_id)):
            for member, stage_read in reads.items():
                if member in errors:
                    continue
                try:
                    with savepoint(conn, _MEMBER_WRITE_SAVEPOINT, owns=False):
                        write(member, stage_read)
                except (LookupError, ValueError) as exc:
                    errors[member] = exc
        conn.commit()
        return errors
    except Exception as exc:
        rollback_after_error(conn, exc)
        raise
