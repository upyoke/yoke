"""Resolve retained execution state under the subject's begin lock."""

from yoke_core.domain.qa_plan_execution_authority import plan_execution_is_abandoned
from yoke_core.domain.qa_plan_execution_continuation import resolve_continuation_source
from yoke_core.domain.qa_plan_execution_lifecycle import (
    STALE_PLAN_EXECUTION_REASON,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_STATES
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    live_plan_execution_id,
    lock_plan_execution,
    resume_owned_plan_execution,
    same_owner,
)
from yoke_core.domain.qa_plan_partition_chains import partition_key
from yoke_core.domain.qa_plan_partition_custody import partition_unavailable


def continuation_source(conn, subject, prepared, expected_execution_id):
    return resolve_continuation_source(
        conn,
        live_execution_id=live_plan_execution_id(
            conn, **subject, execution_target_digest=prepared.execution_target_digest
        ),
        expected_execution_id=expected_execution_id,
        **subject,
    )


def resume_existing(conn, subject, prepared, *, actor_id, partition, requirement_id):
    """Return a resume receipt or whether a retirement committed."""
    from yoke_core.domain.qa_deployment_requirement_identity_schema import shared_group_id

    existing_id = live_plan_execution_id(
        conn, **subject, execution_target_digest=prepared.execution_target_digest,
        group_id=shared_group_id(prepared.execution_target),
    )
    if existing_id is None:
        return None, False
    existing = lock_plan_execution(conn, existing_id)
    if existing["state"] not in LIVE_PLAN_EXECUTION_STATES:
        return None, False
    if (
        (partition and partition_key(existing["roster"]) != partition)
        or (requirement_id is not None and [
            int(row["requirement_id"]) for row in existing["roster"]
        ] != [requirement_id])
    ):
        raise partition_unavailable(
            prepared.partition or "<selected>",
            f"cannot use this session's cursor while execution {existing_id} is live; "
            f"resume it with `yoke qa plan run --resume-execution-id {existing_id}`",
        )
    if same_owner(existing, actor_id=actor_id, session_id=subject["session_id"]):
        from yoke_core.domain.deployment_qa_execution_refreeze import refreeze_unbegun_execution
        from yoke_core.domain.qa_environment_served_build import require_execution_access
        from yoke_core.domain.qa_plan_execution_roster_change import retire_unstarted_changed_roster

        refreeze_unbegun_execution(conn, existing, prepared)
        require_execution_access(conn, existing)
        if retire_unstarted_changed_roster(conn, existing, digest=prepared.digest):
            return None, True
        return {
            **resume_owned_plan_execution(conn, existing, digest=prepared.digest),
            "remaining_requirement_count": prepared.remaining,
        }, False
    if plan_execution_is_abandoned(conn, existing):
        finish_plan_execution(conn, existing, state="aborted", reason=STALE_PLAN_EXECUTION_REASON)
        return None, True
    raise QaPlanExecutionStateError(
        "qa_execution_owner_mismatch: the live cursor has another actor; "
        "ask its owner to use yoke qa plan abort"
    )
