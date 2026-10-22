"""Prepare sources without item locks, then validate and commit run admission."""

from dataclasses import dataclass

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_work import carried_work_for_enrollment
from yoke_core.domain.deployment_run_composition_basis import (
    CompositionBasis,
    lock_snapshot_rows,
    read_composition_basis,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
    member_ids,
    requires_release_admission,
)
from yoke_core.domain.deployment_run_composition_plan import (
    CompositionPlan,
    plan_run_composition,
)
from yoke_core.domain.deployment_run_composition_guard import (
    has_frozen_composition,
    terminal_run_refusal,
)
from yoke_core.domain.deployment_run_contained_items import (
    record_attested_candidate_containment,
)
from yoke_core.domain.deployment_run_project_sources import (
    carried_project_ids,
    invalidate_run_source_facts,
)
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
    validate_deployment_run_members,
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


@dataclass(frozen=True)
class _AdmissionPlan:
    """What admission read before its locks, and the basis proving it current."""

    basis: CompositionBasis
    item_ids: tuple[int, ...]
    member_refusal: Exception | None
    composition: CompositionPlan | None


def _plan_admission(conn, run_id):
    """Ask every question that grows with the run while no lock is held."""
    invalidate_run_source_facts(conn, run_id)
    item_ids = member_ids(conn, run_id)
    try:
        project_ids = carried_project_ids(conn, run_id)
    except LookupError:
        return None
    basis = read_composition_basis(
        conn, run_id, item_ids=item_ids, project_ids=project_ids
    )
    if basis is None:
        return None
    refusal = None
    try:
        validate_deployment_run_members(
            conn, run_id=run_id, item_ids=item_ids, attached=True
        )
    except (LookupError, ValueError) as exc:
        refusal = exc
    return _AdmissionPlan(basis, item_ids, refusal, plan_run_composition(conn, run_id))


def _current_plan(conn, plan, item_ids):
    """The plan when nothing it read has changed, else ``None`` to read again."""
    if plan is None or plan.item_ids != item_ids:
        return None
    if plan.composition is not None:
        lock_snapshot_rows(
            conn, plan.composition.requirement_ids, plan.composition.plan_ids
        )
    return plan if plan.basis.unchanged(conn) else None


def _admit(conn, run_id, candidate_containment):
    with bounded_run_write(conn, run_id), prepared_sources_only():
        # The reads that grow with the run happen before any lock; the locks
        # below cover a constant re-check and the writes.
        plan = timed_call("start_admission_reads", _plan_admission, conn, run_id)
        status, item_ids = timed_call(
            "start_item_run_locks",
            lock_run_with_stable_membership,
            conn,
            run_id,
        )
        if status is None:
            return f"Error: deployment run '{run_id}' not found"
        successor = conn.execute(
            "SELECT superseded_by_run_id FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        if successor:
            return (
                f"Error: deployment_run_superseded: run {run_id} transferred ownership "
                f"to {successor}; continue that successor instead of retrying this run"
            )
        if refusal := terminal_run_refusal(
            run_id,
            status,
            advancing_to="executing",
            action="change status",
        ):
            return refusal
        invalidate_run_source_facts(conn, run_id)
        plan = timed_call(
            "start_admission_recheck", _current_plan, conn, plan, item_ids
        )
        if plan is None:
            validate_deployment_run_members(
                conn, run_id=run_id, item_ids=item_ids, attached=True
            )
        elif plan.member_refusal is not None:
            raise plan.member_refusal
        timed_call("target_occupancy", require_target_unoccupied, conn, run_id)
        timed_call(
            "composition_freeze",
            freeze_run_composition,
            conn,
            run_id,
            plan=plan.composition if plan is not None else None,
        )
        record_attested_candidate_containment(conn, run_id, candidate_containment)
        if status == "failed":
            from yoke_core.domain.qa_deployment_run_settlement import (
                restore_retry_obligations,
            )

            restore_retry_obligations(conn, run_id)
        # A resumed failed run is executing again, so its old completion
        # time no longer describes it.
        conn.execute(
            "UPDATE deployment_runs SET status=%s, started_at=%s, "
            "completed_at=NULL WHERE id=%s",
            ("executing", instant_parameter(conn, utc_now()), run_id),
        )
        timed_call("executing_stamp", conn.commit)
    return None
