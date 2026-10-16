"""Prepare sources without item locks, then validate and commit run admission."""

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_work import carried_work_for_enrollment
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
    requires_release_admission,
)
from yoke_core.domain.deployment_run_composition_guard import (
    has_frozen_composition,
    terminal_run_refusal,
)
from yoke_core.domain.deployment_run_contained_items import (
    record_attested_candidate_containment,
)
from yoke_core.domain.deployment_run_project_sources import invalidate_run_source_facts
from yoke_core.domain.deployment_run_unheld_candidates import candidate_custody
from yoke_core.domain.deployment_runs_lock import (
    bounded_run_write,
    lock_run_with_stable_membership,
)
from yoke_core.domain.deployment_source_reads import (
    prepared_sources_only,
    SourcePreparationChanged,
)
from yoke_core.domain.deployment_start_timing import timed_call
from yoke_core.domain.deploy_target_occupancy import require_target_unoccupied
from yoke_core.domain.schema_read_scope import composition_operation
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_items,
)


def _prepare(conn, run_id):
    row = conn.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    if refusal := terminal_run_refusal(
        run_id, row[0], advancing_to="executing", action="change status"
    ):
        raise ValueError(refusal)
    if not requires_release_admission(conn, run_id) or has_frozen_composition(
        conn, run_id
    ):
        return
    with bounded_run_write(conn, run_id):
        record_bound_sources(conn, run_id)
    # The pin is forward-only. Commit it before any further provider work so
    # another request never waits behind a network call on this run's row.
    conn.commit()
    carried_work_for_enrollment(conn, run_id)
    candidate_custody(conn, run_id)


_SOURCE_PREPARATIONS = 8


@composition_operation
def start_run(conn, run_id, candidate_containment):
    try:
        timed_call("start_source_preparation", _prepare, conn, run_id)
        for attempt in range(1, _SOURCE_PREPARATIONS + 1):
            try:
                return _admit(conn, run_id, candidate_containment)
            except SourcePreparationChanged as exc:
                conn.rollback()
                if attempt == _SOURCE_PREPARATIONS:
                    return (
                        f"Error: {exc} The question was still new after "
                        f"{_SOURCE_PREPARATIONS} unlocked preparations."
                    )
                # Answer only the new exact question with every lock released,
                # then reread the mutable facts under fresh locks.
                timed_call("start_source_refresh", exc.prepare)
    except (LookupError, ValueError) as exc:
        conn.rollback()
        return f"Error: {exc}"


def _admit(conn, run_id, candidate_containment):
    with bounded_run_write(conn, run_id), prepared_sources_only():
        status, item_ids = timed_call(
            "start_item_run_locks",
            lock_run_with_stable_membership,
            conn,
            run_id,
        )
        if status is None:
            return f"Error: deployment run '{run_id}' not found"
        if refusal := terminal_run_refusal(
            run_id,
            status,
            advancing_to="executing",
            action="change status",
        ):
            return refusal
        invalidate_run_source_facts(conn, run_id)
        validate_deployment_run_items(conn, run_id=run_id, item_ids=item_ids)
        timed_call("target_occupancy", require_target_unoccupied, conn, run_id)
        timed_call("composition_freeze", freeze_run_composition, conn, run_id)
        record_attested_candidate_containment(conn, run_id, candidate_containment)
        if status == "failed":
            from yoke_core.domain.qa_deployment_run_settlement import (
                restore_retry_obligations,
            )

            restore_retry_obligations(conn, run_id)
        conn.execute(
            "UPDATE deployment_runs SET status=%s, started_at=%s WHERE id=%s",
            ("executing", instant_parameter(conn, utc_now()), run_id),
        )
        timed_call("executing_stamp", conn.commit)
    return None
