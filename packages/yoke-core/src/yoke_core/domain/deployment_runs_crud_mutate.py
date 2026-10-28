"""Run creation, membership mutation, transitions, and success bookkeeping."""

from __future__ import annotations

from yoke_core.domain.deployment_start_timing import timed_call

from collections.abc import Iterable
from typing import Any, Mapping, Optional

from yoke_core.domain.db_helpers import connect, instant_parameter, utc_now
from yoke_core.domain import deployment_run_lineage_rebind as lineage_rebind
from yoke_core.domain import (
    deployment_run_completion_preconditions as completion_preconditions,
)
from yoke_core.domain.deployment_run_create_write import (
    CompositionRefused,
    cmd_create_run,
    create_run,
)
from yoke_core.domain.deployment_run_id_allocation import cmd_next_id
from yoke_core.domain.deployment_runs_schema import (
    UPDATABLE_FIELDS,
    VALID_STATUSES,
)
from yoke_core.domain.deployment_run_composition_guard import (
    frozen_mutation_refusal,
    has_frozen_composition,
    mutable_field_refusal,
    terminal_run_refusal,
)
from yoke_core.domain.deployment_run_membership_removals import (
    clear_membership_removal,
)
from yoke_core.domain.deployment_runs_lock import (
    bounded_run_write,
    lock_run,
    lock_run_with_stable_membership,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_members,
)
from yoke_core.domain.deployment_run_member_removal import cmd_remove_item


def _require_composable_run(conn, run_id: str) -> None:
    status = lock_run(conn, run_id)
    if status is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    if status != "created":
        raise ValueError(
            f"deployment run '{run_id}' is {status}; membership is mutable "
            "only while status='created'"
        )
    if has_frozen_composition(conn, run_id):
        raise ValueError(frozen_mutation_refusal(run_id, "membership")[7:])


def cmd_add_item(
    run_id: str,
    item_id: int,
    db_path: Optional[str] = None,
    *,
    delivery_intent: Optional[str] = None,
    requirement_ids: Iterable[int] = (),
) -> str:
    """Add item to run. Returns confirmation message."""
    conn = connect(db_path)
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        _require_composable_run(conn, run_id)
        from yoke_core.domain.deployment_run_member_admission import (
            admit_run_item,
        )
        from yoke_core.domain.deployment_run_item_qa_membership import (
            require_item_qa_membership_possible,
        )

        # Refused before the attach: a member the run can never snapshot
        # would otherwise surface only as a broken snapshot at item QA.
        require_item_qa_membership_possible(conn, run_id)

        ref = admit_run_item(
            conn,
            run_id=run_id,
            item_id=int(item_id),
            delivery_intent=delivery_intent,
            requirement_ids=requirement_ids,
        )
        # Attaching reverses an earlier removal; left in place it would keep
        # composition subtracting the member this call just admitted.
        clear_membership_removal(conn, run_id, int(item_id))
        from yoke_core.domain.deployment_member_post_deploy_admission import (
            unadmitted_post_deploy_notice,
        )
        from yoke_core.domain.deployment_member_run_coverage import (
            member_coverage_notice,
        )

        # Said before the commit returns, because an obligation this run
        # cannot discharge is what will block the item's done transition
        # long after the add looked like it succeeded.
        unadmitted = unadmitted_post_deploy_notice(
            conn, run_id, item_ids=(int(item_id),)
        )
        # And said for the same reason one step earlier: what this run can
        # check and can close is what the membership is for, and the attach
        # is the last moment the caller can choose a run that does either.
        coverage = member_coverage_notice(conn, run_id=run_id, item_id=int(item_id))
        from yoke_core.domain.deployment_item_completion_runs import (
            uncredited_supplemental_notice,
        )

        uncredited = uncredited_supplemental_notice(
            conn, run_id=run_id, item_id=int(item_id)
        )
        conn.commit()
        notes = [note for note in (coverage, uncredited, unadmitted) if note]
        return " ".join([f"Added {ref} to run {run_id}.", *notes])
    finally:
        conn.close()


def cmd_update(
    run_id: str,
    field: str,
    value: str,
    force: bool = False,
    db_path: Optional[str] = None,
    candidate_containment: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Update a run column. Returns error message on failure, None on success.

    Auto-sets timestamps and validates status=succeeded cross-field consistency.
    """
    if field not in UPDATABLE_FIELDS:
        return f"Error: field '{field}' is not updatable"

    conn = connect(db_path)
    try:
        if field == "status" and value == "executing":
            from yoke_core.domain.deployment_run_start import start_run

            return start_run(conn, run_id, candidate_containment)
        if field == "status":
            try:
                with bounded_run_write(conn, run_id):
                    status, item_ids = lock_run_with_stable_membership(conn, run_id)
            except ValueError as exc:
                return f"Error: {exc}"
            if status is None:
                return f"Error: deployment run '{run_id}' not found"
            if value not in VALID_STATUSES:
                return f"Error: invalid status '{value}'"
            if refusal := terminal_run_refusal(
                conn, run_id, status, advancing_to=value, action="change status"
            ):
                return refusal
            if value == "created" and has_frozen_composition(conn, run_id):
                return frozen_mutation_refusal(run_id, "status")
            if value in {"created", "executing"}:
                try:
                    validate_deployment_run_members(
                        conn,
                        run_id=run_id,
                        item_ids=item_ids,
                        attached=True,
                    )
                except ValueError as exc:
                    return f"Error: {exc}"

            if value == "succeeded" and (
                refusal := completion_preconditions.refuse_succeeded(
                    conn, run_id, force=force
                )
            ):
                return refusal

            if value in ("succeeded", "failed", "cancelled"):
                if value == "succeeded":
                    from yoke_core.domain.deployment_run_collective_finalization import (
                        mark_settling,
                        settle_members,
                    )

                    # Every cleared member closes before the run may read
                    # succeeded, and they close together or not at all.
                    # Settling is durable and non-terminal, so a refusal or an
                    # interruption here is replayed by the next re-drive
                    # rather than leaving a green run behind.
                    from yoke_core.domain.settling_run_replay import (
                        settlement_in_progress,
                    )

                    mark_settling(conn, run_id)
                    with settlement_in_progress():
                        refusal = timed_call(
                            "member_settlement", settle_members, conn, run_id
                        )
                    if refusal:
                        return refusal
                    from yoke_core.domain.deployment_run_settle_success import (
                        read_success,
                        succeed_run_on,
                    )

                    # Members' attributions and the carried-work comparison
                    # are read before the run row lock, which then covers a
                    # one-statement re-check and the writes. A delivered run
                    # keeps its carried-work answer, so no reader derives it.
                    succeed_run_on(conn, run_id, read_success(conn, run_id))
                else:
                    # A failed or cancelled run derives no carried work under
                    # this row lock; a read derives it if the freeze never did.
                    conn.execute(
                        "UPDATE deployment_runs SET status=%s, completed_at=%s "
                        "WHERE id=%s",
                        (value, instant_parameter(conn, utc_now()), run_id),
                    )
                preserved = False
                if value in {"failed", "cancelled"}:
                    from yoke_core.domain.qa_deployment_run_settlement import (
                        settle_unsuccessful_run,
                    )

                    preserved = settle_unsuccessful_run(
                        conn, run_id, reason=f"deployment run {run_id} {value}"
                    )
                from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
                    withdraw_deployment_qa_wait_wakes,
                )

                if not preserved:
                    withdraw_deployment_qa_wait_wakes(
                        conn, run_id=run_id, reason=f"run_terminal:{value}"
                    )
                conn.commit()
                if value in {"failed", "cancelled"}:
                    from yoke_core.domain.deployment_run_workflow_cancellation import (
                        cancel_run_workflows,
                    )

                    # After the commit: the close stands even when GitHub
                    # cannot be reached, and each miss is logged with its fix.
                    cancel_run_workflows(conn, run_id)
                if value == "succeeded":
                    from yoke_core.domain.deployment_delivery_close_out_notice import (
                        notify_delivery_cleared,
                    )

                    # Strictly after the status commit. A member still at its
                    # pinned release wait is held by a session parked on
                    # exactly this event, but announcing it is downstream of
                    # the run's own record: on Postgres one failed send would
                    # abort the transaction carrying 'succeeded' and lose the
                    # delivery this is announcing.
                    notify_delivery_cleared(conn, run_id=run_id)
                return None
        elif field == lineage_rebind.LINEAGE_FIELD and (
            refusal := lineage_rebind.refuse_lineage_write(conn, run_id, value)
        ):
            return refusal
        else:
            status = lock_run(conn, run_id)
            if status is None:
                return f"Error: deployment run '{run_id}' not found"
            if field == "current_stage" and (
                refusal := terminal_run_refusal(
                    conn,
                    run_id,
                    status,
                    advancing_to=value,
                    action="advance to a new stage",
                )
            ):
                return refusal
            if field in {"artifact_identity", "composition_resolution"} and (
                refusal := mutable_field_refusal(conn, run_id, field, status)
            ):
                return refusal

        if field == "current_stage":
            from yoke_core.domain.deployment_run_stage_entry import set_current_stage

            set_current_stage(conn, run_id, value)
        else:
            conn.execute(
                f"UPDATE deployment_runs SET {field}=%s WHERE id=%s",
                (value, run_id),
            )
        conn.commit()
        return None
    finally:
        conn.close()


__all__ = [
    "CompositionRefused",
    "cmd_add_item",
    "cmd_create_run",
    "create_run",
    "cmd_next_id",
    "cmd_remove_item",
    "cmd_update",
]
