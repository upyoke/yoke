"""Persist unproven ordinary restoration before host custody can end."""

import json

from yoke_core.domain.machine_reset_debt import record_reset_owed
from yoke_core.domain.qa_plan_execution_abort_state import restore_cleanup_proven


def record_unproven_restore(conn, *, case, test_machine, lease_id, restore):
    restore = restore if isinstance(restore, dict) else {}
    baseline = case.get("host_baseline")
    if baseline and restore_cleanup_proven(restore, baseline):
        return
    if not baseline and restore and not restore.get("error_code"):
        return  # An as-is chain proves cleanup with its no-restore receipt.
    record_reset_owed(conn, case=case, test_machine=test_machine, lease_id=lease_id)


def record_restore_artifact(conn, requirement_id, run_id, content, actor):
    """A current mission's restore artifact carries its cleanup outcome."""
    from yoke_core.domain.coordination_claims import (
        get_claim,
        CoordinationClaimNotFoundError,
    )
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.machine_qa_submission_recording import _json_object
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context

    row = query_one(
        conn,
        "SELECT raw_result FROM qa_runs WHERE id=%s AND qa_requirement_id=%s",
        (run_id, requirement_id),
    )
    raw = _json_object(row["raw_result"]) if row else {}
    submission = (
        raw.get("host_control_submission")
        or _json_object(raw.get("evidence")).get("host_control_submission")
        or {}
    )
    lease_id = submission.get("lease_id")
    if not isinstance(lease_id, int) or isinstance(lease_id, bool):
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
        return  # Historical evidence cannot change a later holder's host state.
    try:
        restore = json.loads(content) if content is not None else None
    except (ValueError, TypeError):
        restore = None
    case = get_case_execution_context(conn, requirement_id=requirement_id)
    record_unproven_restore(
        conn,
        case=case,
        test_machine=lease.target.test_machine,
        lease_id=lease.id,
        restore=restore,
    )
