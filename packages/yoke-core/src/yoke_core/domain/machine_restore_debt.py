"""Persist ordinary mission restoration before host custody can end."""

import json

from yoke_contracts.machine_qa_host_control import HOST_BASELINES, RESET_OWED_OPERATION
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.machine_operation_recording import (
    record_test_machine_operation,
    recorded_test_machine_operation,
)
from yoke_core.domain.machine_reset_debt import record_reset_owed, reset_owed
from yoke_core.domain.qa_plan_execution_abort_state import (
    case_restore_proven,
    restore_cleanup_proven,
)


def record_unproven_restore(conn, *, case, test_machine, lease_id, restore):
    restore = restore if isinstance(restore, dict) else {}
    baseline = case.get("host_baseline")
    if baseline and restore_cleanup_proven(restore, baseline):
        return
    record_reset_owed(conn, case=case, test_machine=test_machine, lease_id=lease_id)


def record_restore_artifact(
    conn, requirement_id, run_id, content, actor, *, new_artifact_id
):
    """Accept a current mission's restore while its original holder has custody."""
    from yoke_core.domain.coordination_claims import (
        get_claim,
        CoordinationClaimNotFoundError,
    )
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.machine_qa_submission_recording import _json_object
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context
    from yoke_core.domain.qa_host_turns import lock_host_turn

    row = query_one(
        conn,
        "SELECT raw_result FROM qa_runs r WHERE r.id=%s AND r.qa_requirement_id=%s "
        "AND r.performed_by='agent_mission' AND NOT EXISTS ("
        "SELECT 1 FROM qa_runs newer WHERE newer.qa_requirement_id=r.qa_requirement_id "
        "AND newer.performed_by='agent_mission' AND newer.id>r.id)",
        (run_id, requirement_id),
    )
    raw = _json_object(row["raw_result"]) if row else {}
    submission = (
        raw.get("host_control_submission")
        or _json_object(raw.get("evidence")).get("host_control_submission")
        or {}
    )
    lease_id = submission.get("lease_id")
    digest = submission.get("contract_digest")
    if type(lease_id) is not int or not isinstance(digest, str) or not digest:
        return
    try:
        lease = get_claim(conn, lease_id)
    except CoordinationClaimNotFoundError:
        return
    if lease.session_id != actor.session_id or str(lease.actor_id) != str(
        actor.actor_id
    ):
        return
    if not lease.is_active or not lease.target.test_machine:
        return
    # Hand-back has already taken any execution lock. Serialize with host release
    # before checking custody again and reading or replacing the current receipt.
    lock_host_turn(conn, lease.target)
    if not get_claim(conn, lease_id).is_active:
        return

    first_restore = query_one(
        conn,
        "SELECT id, created_at FROM qa_artifacts WHERE qa_run_id=%s "
        "AND artifact_type='starting_state_restore' ORDER BY id LIMIT 1",
        (run_id,),
    )
    if first_restore is None:
        return
    try:
        restore = json.loads(content) if content is not None else {}
    except (ValueError, TypeError):
        restore = {}
    if not isinstance(restore, dict):
        restore = {}
    case = get_case_execution_context(
        conn, requirement_id=requirement_id, include_waived=True
    )
    test_machine = lease.target.test_machine
    first_recorded_at = parse_instant(first_restore["created_at"])
    if not case_restore_proven(case, restore):
        if first_restore["id"] == new_artifact_id:
            # The first artifact and its debt share one durable instant. Later
            # failures or replays cannot give this run ownership of newer debt.
            record_reset_owed(
                conn,
                case=case,
                test_machine=test_machine,
                lease_id=lease_id,
                contract_digest=digest,
                performed_at=first_recorded_at,
            )
        return
    baseline = case.get("host_baseline")
    if baseline not in HOST_BASELINES or case.get("starting_state") == "as_is":
        return
    if restore.get("ok") is not True or restore.get("error_code"):
        return
    debt = recorded_test_machine_operation(
        conn,
        test_machine=test_machine,
        operation=RESET_OWED_OPERATION,
        lease_id=lease_id,
        contract_digest=digest,
    )
    if (
        debt is None
        or debt["performed_at"] != first_recorded_at
        or reset_owed(conn, test_machine) != baseline
    ):
        return
    record_test_machine_operation(
        conn,
        test_machine=test_machine,
        operation="reset",
        status="verified",
        checks=[{"name": baseline, "ok": True}],
        error_code=None,
        lease_id=lease_id,
        contract_digest=digest,
        commit=False,
    )
