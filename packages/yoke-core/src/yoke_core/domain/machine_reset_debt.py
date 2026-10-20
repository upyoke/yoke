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


def reset_owed(conn, machine, *, include_resolved=False):
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
    return owed["checks"][0]["name"] if include_resolved or not cleared else None


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
    if receipt.get("baseline") != baseline:
        raise ValueError(
            "machine_reset_proof_missing: rerun the case to record its owed reset"
        )
    ok = receipt.get("ok") is True
    record_test_machine_operation(
        conn,
        contract.project_id,
        machine=contract.settings["resource_name"],
        operation="reset",
        status="verified" if ok else "error",
        checks=[{"name": baseline, "ok": ok, **receipt}],
        error_code=None if ok else "machine_needs_repair",
        lease_id=contract.lease_id,
        contract_digest=contract.contract_digest,
        commit=False,
    )


def recovery_receipt_matches(conn, machine, lease_id, digest):
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
    return bool(
        receipt and receipt["status"] == "verified" and not receipt["error_code"]
    )
