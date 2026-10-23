"""Durable reset debt and its recovery, owned by machine operation receipts."""

from yoke_contracts.machine_qa_host_control import RESET_OWED_OPERATION
from yoke_contracts.machine_config.test_machine import test_machine_capability_type
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.machine_operation_recording import (
    _marker,
    _row_result,
    record_test_machine_operation,
)


def reset_command(project, machine, baseline):
    import shlex

    return shlex.join(
        [
            "yoke",
            "test-machine",
            "reset",
            "--project",
            str(project),
            "--test-machine",
            machine,
            "--baseline",
            baseline,
        ]
    )


def reset_owed(conn, machine):
    """Physical hosts share debt across projects, just as they share custody."""
    p = _marker(conn)
    rows = conn.execute(
        "SELECT operation,status,performed_at,receipt_json,error_code "
        "FROM test_machine_operation_receipts "
        f"WHERE capability_type={p} AND operation IN ({p},{p}) "
        "ORDER BY performed_at DESC",
        (test_machine_capability_type(machine), RESET_OWED_OPERATION, "reset"),
    ).fetchall()
    receipts = [_row_result(row) for row in rows]
    owed = next((r for r in receipts if r["operation"] == RESET_OWED_OPERATION), None)
    if owed is None:
        return None
    cleared = any(
        r["operation"] == "reset"
        and r["status"] == "verified"
        and not r["error_code"]
        and r["checks"]
        and all(c.get("ok") is True for c in r["checks"])
        and parse_instant(r["performed_at"]) > parse_instant(owed["performed_at"])
        for r in receipts
    )
    return owed["checks"][0]["name"] if not cleared else None


def record_reset_owed(conn, *, case, machine, lease_id, contract_digest=""):
    baseline = case.get("host_baseline")
    if not baseline:
        return  # Preserving an as-is host grants no baseline reset authority.
    return record_test_machine_operation(
        conn,
        int(case["project_id"]),
        machine=machine,
        operation=RESET_OWED_OPERATION,
        status="error",
        checks=[{"name": baseline, "ok": False}],
        error_code="machine_reset_owed",
        lease_id=lease_id,
        contract_digest=contract_digest,
        commit=False,
    )


def record_owed_reset(conn, contract, evidence):
    """Accept recovery proof only for the baseline this contract required."""
    baseline = contract.reset_owed_baseline
    if not baseline:
        return
    receipt = evidence.get("owed_reset") or {}
    unstarted = evidence.get("case_started") is False or bool(
        evidence.get("preparation_failure")
    )
    if not receipt and unstarted:
        return
    if receipt.get("baseline") != baseline:
        raise ValueError(
            "machine_reset_proof_missing: rerun the case to record its owed reset"
        )
    ok = receipt.get("ok") is True
    if not ok and not unstarted:
        raise ValueError(
            "machine_needs_repair: failed owed reset cannot authorize case work; run "
            + reset_command(
                contract.project, contract.settings["resource_name"], baseline
            )
        )
    record_test_machine_operation(
        conn,
        contract.project_id,
        machine=contract.settings["resource_name"],
        operation="reset",
        status="verified" if ok else "error",
        checks=[{**receipt, "name": baseline, "ok": ok}],
        error_code=None if ok else "machine_needs_repair",
        lease_id=contract.lease_id,
        contract_digest=contract.contract_digest,
        commit=False,
    )


def recovered_submission_contract(conn, lease_id, digest, expected):
    """Reconstruct an accepted contract from its durable capture identity."""
    import hmac
    from yoke_contracts.machine_qa_execution import (
        execution_contract_digest,
        HOST_BASELINES,
    )
    from yoke_contracts.qa_continuity_fingerprint import execution_protocol
    from yoke_core.domain.host_control_submission_receipt import (
        host_control_submission_receipt_matches,
    )
    from yoke_core.domain.machine_qa_submission_recording import _json_object

    for case in expected.cases:
        rows = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE qa_requirement_id=%s "
            "AND performed_by IN ('host_control','agent_mission') ORDER BY id",
            (case.requirement_id,),
        ).fetchall()
        for row in rows:
            raw = _json_object(row["raw_result"])
            evidence = _json_object(raw.get("evidence"))
            receipt = raw.get("host_control_submission") or evidence.get(
                "host_control_submission"
            )
            if not host_control_submission_receipt_matches(
                receipt, lease_id=lease_id, contract_digest=digest
            ):
                continue
            baseline = receipt.get("reset_owed_baseline")
            if baseline is not None and baseline not in HOST_BASELINES:
                return None
            recovered = expected.model_copy(
                update={
                    "reset_owed_baseline": baseline,
                    "contract_digest": digest,
                    "protocol": "host-control-reset-recovery-v1"
                    if baseline
                    else execution_protocol(expected.cases),
                }
            )
            return (
                recovered
                if hmac.compare_digest(execution_contract_digest(recovered), digest)
                else None
            )
    return None


def record_execution_reset_debt(conn, execution, leases):
    """Custody lost without cleanup owes the interrupted case's baseline."""
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request

    roster = execution.get("roster") or []
    if not roster:
        raise ValueError(
            "qa_host_reset_context_missing: inspect this execution's missing roster "
            "with the control-plane operator before releasing its host"
        )
    abort = abort_request(execution) or {}
    ordinal = int(abort.get("ordinal", execution["cursor_ordinal"]))
    case = roster[min(ordinal, len(roster) - 1)]
    for candidate in reversed(roster[: ordinal + 1]):
        if candidate.get("runner_id") in {"host_control", "agent_mission"} or (
            candidate.get("method_config") or {}
        ).get("test_machine"):
            case = candidate
            break
    for lease in leases:
        record_reset_owed(
            conn,
            case=case,
            machine=lease.target.test_machine,
            lease_id=lease.id,
        )
