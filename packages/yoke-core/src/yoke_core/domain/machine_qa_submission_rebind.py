"""Validate and credit single-case evidence across a successor's target rebind."""

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.deployment_qa_requirement_target_refresh import (
    credit_rebound_pass,
)
from yoke_core.domain.deployment_qa_takeover_identity import inherited_rebind
from yoke_core.domain.deployment_qa_target_continuity import evidence_target_matches
from yoke_core.domain.deployment_qa_target_reads import _decode_stored_target
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaContractChanged,
    validate_host_control_submission,
)
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_requirement_scope import lock_requirement_scope


def lock_case_rebind(conn, requirement_id):
    """Serialize submission with takeover and target refresh on the requirement row."""
    postgres = db_backend.connection_is_postgres(conn)
    if postgres:
        lock_requirement_scope(conn, requirement_id)
    elif not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    return query_one(
        conn,
        "SELECT rebound_at,rebound_from_target_json FROM qa_requirements "
        + ("WHERE id=%s FOR NO KEY UPDATE" if postgres else "WHERE id=?"),
        (requirement_id,),
    )


def validate_single_case_submission(conn, case, *, rebind, actor, parsed, baselines):
    scope = {
        "project": str(case["project"]),
        "session_id": actor.session_id,
        "actor_id": actor.actor_id,
        "lease_id": parsed.lease_id,
        "contract_digest": parsed.contract_digest,
        "operation": "case",
        "baselines": tuple(baselines),
        "allow_recorded_replay": True,
    }
    try:
        lease, contract = validate_host_control_submission(conn, cases=(case,), **scope)
    except MachineQaContractChanged:
        frozen = (
            _decode_stored_target(rebind["rebound_from_target_json"])
            if rebind and rebind["rebound_at"]
            else None
        )
        if frozen is None or not inherited_rebind(
            conn, str(case["deployment_run_id"] or ""), frozen, case["execution_target"]
        ):
            raise
        case = {
            **case,
            "execution_target": frozen,
            "execution_target_digest": target_digest(frozen),
        }
        lease, contract = validate_host_control_submission(conn, cases=(case,), **scope)
    return case, lease, contract


def credit_single_case_pass(conn, *, submitted_case, current_case):
    if (
        submitted_case["execution_target_digest"]
        == current_case["execution_target_digest"]
    ):
        return
    run_id = str(current_case["deployment_run_id"])
    if evidence_target_matches(
        conn,
        run_id,
        submitted_case["execution_target"],
        current_case["execution_target"],
    ):
        credit_rebound_pass(
            conn,
            requirement_id=int(current_case["requirement_id"]),
            run_id=run_id,
            current_digest=current_case["execution_target_digest"],
            recorded_digest=submitted_case["execution_target_digest"],
        )
