"""Apply prepared QA subjects under their run lock, then release the lock.

The read stays outside the lock: a run that changed since it is read again
unlocked (:func:`lock_current_read`), so no run-wide query, git or HTTP call
ever runs while this writer holds the run row. Each member commits separately,
so workers can settle their QA between writes.
"""

from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error
from yoke_core.domain.deployment_runs_lock import (
    lock_current_read,
    lock_run,
    run_lock_held,
    run_lock_is_held,
)


def _write_subject(conn, stage_read, *, member, replaced_requirement_ids):
    from yoke_core.domain.deployment_qa_snapshot_selection import freeze_selected_plans
    from yoke_core.domain.deployment_qa_subject_materialization import (
        materialize_subject,
    )

    if stage_read.selected_admission is not None:
        return stage_read.selected_admission
    freeze_selected_plans(conn, stage_read.subject, stage_read.snapshots)
    return materialize_subject(
        conn,
        subject=stage_read.subject,
        target=stage_read.target,
        admitted=stage_read.admitted,
        snapshots=stage_read.snapshots,
        commit=False,
        replaced_requirement_ids=replaced_requirement_ids,
        refresh_target=stage_read.refresh_target,
    )


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
        # A dispatch already validated this member under its short run lock.
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
        if not run_lock_is_held(conn, str(run_id)):
            stage_read.projection.advance(conn)
        if commit:
            conn.commit()
        return result
    except Exception as exc:
        if commit:
            rollback_after_error(conn, exc)
        raise


def write_under_run_lock(conn, run_id, write):
    """Run one write under the run lock and commit it."""
    try:
        lock_run(conn, str(run_id))
        write()
        conn.commit()
    except Exception as exc:
        rollback_after_error(conn, exc)
        raise


def write_prepared_cohort(conn, *, run_id, read, write, reread, then=None):
    """Read unlocked, then validate and commit each member under a short lock.

    A changed member is read again without the lock; other members' verdicts
    leave its prepared read valid. Plan groups have their own transaction.
    """
    from yoke_core.domain.deployment_qa_presentation_reads import uncached_presentation

    from yoke_core.domain.deployment_qa_stage_materialization import _require_member_still_attached

    reads, errors = read()
    errors = dict(errors)
    for member, prepared in reads.items():

        def read_current():
            with uncached_presentation():
                _require_member_still_attached(conn, run_id, member)
                return reread(member)

        try:
            current = lock_current_read(
                conn,
                str(run_id),
                read_current,
                prepared=prepared,
                holds=lambda current: current.projection.holds(conn),
            )
            with run_lock_held(conn, str(run_id)):
                write(member, current)
                current.projection.advance(conn)
            conn.commit()
        except (LookupError, ValueError) as exc:
            rollback_after_error(conn, exc)
            errors[member] = exc
        except Exception as exc:
            rollback_after_error(conn, exc)
            raise
    if then is not None:
        write_under_run_lock(conn, run_id, then)
    return errors
