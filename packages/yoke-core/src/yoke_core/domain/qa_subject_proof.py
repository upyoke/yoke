"""Proof for the frozen subject of a selected actual QA execution.

Reuse issued host leases, admitted case/results and command target snapshots.
These are derived checks over existing records, never a new stored status.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.qa_requirement_pass_currency import (
    canonical_method_config,
    executable_method_config,
    recorded_execution_target_digest,
)

MACHINE_RUNNERS = frozenset({"host_control", "agent_mission"})


def proof_subject(requirement: Mapping[str, Any]) -> str:
    """Use the frozen runner/config contract, never a display label."""
    runner = requirement.get("runner_id")
    if runner in MACHINE_RUNNERS:
        return "machine"
    config = executable_method_config(requirement.get("method_config"))
    if runner == "worktree_run" and config.get("requires_base_url") is True:
        return "endpoint"
    return "code"


def requires_code_identity(requirement: Mapping[str, Any]) -> bool:
    return proof_subject(requirement) == "code"


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _machine_proof_error(
    conn: Any, requirement: Mapping[str, Any], run: Mapping[str, Any]
) -> str:
    from yoke_core.domain.coordination_claims import (
        CoordinationClaimNotFoundError,
        get_claim,
    )
    from yoke_core.domain.machine_qa_execution_protocol import (
        HOST_CONTROL_SUBMISSION_RECEIPT_KEY,
    )
    from yoke_core.domain.work_claim_targets import TARGET_KIND_QA_ADMISSION

    raw = _object(run.get("raw_result"))
    evidence = _object(raw.get("evidence"))
    receipt = _object(
        evidence.get(HOST_CONTROL_SUBMISSION_RECEIPT_KEY)
        or raw.get(HOST_CONTROL_SUBMISSION_RECEIPT_KEY)
    )
    try:
        lease = get_claim(conn, int(receipt.get("lease_id")))
    except (TypeError, ValueError, CoordinationClaimNotFoundError):
        return "qa_machine_proof_missing: the actual capture has no issued host lease"
    if (
        not receipt.get("contract_digest")
        or lease.target.kind != TARGET_KIND_QA_ADMISSION
        or not lease.target.machine_id
    ):
        return "qa_machine_contract_unproven: the capture lacks its issued machine contract"
    if run.get("performed_by") != requirement.get("runner_id"):
        return "qa_machine_capture_unproven: the selected attempt was not captured by its frozen runner"
    p = marker(conn)
    if requirement.get("runner_id") == "host_control":
        if evidence.get("machine") != lease.target.machine_id:
            return "qa_machine_resource_mismatch: the actual capture names a different leased resource"
        artifacts = query_rows(
            conn,
            f"SELECT id FROM qa_artifacts WHERE qa_run_id={p} AND artifact_type='machine_evidence'",
            (int(run["id"]),),
        )
        if artifacts and evidence.get("baseline") == requirement.get("host_baseline"):
            # A direct case is a first-class issued-contract execution and has
            # no plan result. Its canonical artifact belongs to this capture.
            return ""
    rows = query_rows(
        conn,
        "SELECT result.ordinal,result.result_json,execution.roster_json,execution.session_id,"
        "execution.item_id,execution.deployment_run_id,execution.transition_id,"
        "execution.execution_target_digest FROM qa_plan_execution_results result "
        "JOIN qa_plan_executions execution ON execution.id=result.execution_id "
        f"WHERE result.requirement_id={p}",
        (int(requirement["id"]),),
    )
    for row in rows:
        result = _object(row["result_json"])
        if result.get("run_id") != run["id"] or row["session_id"] != lease.session_id:
            continue
        if row["item_id"] != requirement.get("item_id") or row[
            "deployment_run_id"
        ] != requirement.get("deployment_run_id"):
            continue
        if row["transition_id"] != requirement.get("workflow_transition_id"):
            continue
        try:
            roster = json.loads(row["roster_json"])
            case = roster[int(row["ordinal"])]
        except (ValueError, TypeError, IndexError, KeyError):
            continue
        if (
            case.get("requirement_id") == requirement["id"]
            and case.get("runner_id") == requirement.get("runner_id")
            and case.get("host_baseline") == requirement.get("host_baseline")
            and canonical_method_config(case.get("method_config"))
            == canonical_method_config(requirement.get("method_config"))
            and str(row["execution_target_digest"] or "")
            == recorded_execution_target_digest(run.get("raw_result"))
        ):
            return ""
    return "qa_machine_admission_unproven: no admitted case result binds this exact capture, frozen baseline and host lease"


def subject_proof_error(
    conn: Any, requirement: Mapping[str, Any], run: Mapping[str, Any]
) -> str:
    """Validate resource proof; code/build identity is checked by its gate."""
    subject = proof_subject(requirement)
    if subject == "machine":
        return _machine_proof_error(conn, requirement, run)
    if subject == "endpoint":
        from yoke_core.domain.qa_project_execution_target import (
            resolve_execution_base_url,
        )

        raw = _object(run.get("raw_result"))
        target = _object(requirement.get("execution_target_json"))
        observed = str(raw.get("base_url") or "").rstrip("/")
        if not observed or not target or not recorded_execution_target_digest(raw):
            return "qa_endpoint_proof_missing: the actual command did not record its observed endpoint and frozen target"
        try:
            resolved = resolve_execution_base_url(target, [requirement], observed)
        except (ValueError, KeyError) as exc:
            return f"qa_endpoint_proof_mismatch: {exc}"
        if (
            run.get("performed_by") != requirement.get("runner_id")
            or resolved != observed
        ):
            return "qa_endpoint_execution_unproven: the selected command does not prove its own endpoint"
    return ""
