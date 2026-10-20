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
            "--machine",
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
    return record_test_machine_operation(
        conn,
        int(case["project_id"]),
        machine=machine,
        operation=RESET_OWED_OPERATION,
        status="error",
        checks=[{"name": case.get("host_baseline") or "fresh-host", "ok": False}],
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


def recovered_submission_contract(conn, machine, lease_id, digest, expected):
    """Reconstruct only the exact contract whose recovery already committed."""
    import hmac
    from yoke_contracts.machine_qa_execution import execution_contract_digest
    from yoke_core.domain.machine_operation_recording import (
        recorded_test_machine_operation,
    )

    receipt = recorded_test_machine_operation(
        conn,
        machine.project_id,
        machine=machine.settings["resource_name"],
        operation="reset",
        lease_id=lease_id,
        contract_digest=digest,
    )
    if not receipt or receipt["status"] != "verified" or receipt["error_code"]:
        return None
    baseline = receipt["checks"][0]["name"]
    recovered = expected.model_copy(
        update={
            "reset_owed_baseline": baseline,
            "protocol": "host-control-reset-recovery-v1",
            "contract_digest": digest,
        }
    )
    return (
        recovered
        if hmac.compare_digest(execution_contract_digest(recovered), digest)
        else None
    )


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
    for lease in leases:
        record_reset_owed(
            conn,
            case=case,
            machine=lease.target.machine_id,
            lease_id=lease.id,
        )
