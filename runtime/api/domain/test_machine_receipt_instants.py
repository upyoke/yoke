"""Machine receipt SQL, replay and JSON keep precise clocks and opaque evidence."""

import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from yoke_contracts.timestamps import parse_instant, temporal_wire
from yoke_contracts.machine_config.test_machine import (
    test_machine_capability_type as machine_type,
)
from yoke_core.domain import machine_operation_recording as operations
from yoke_core.domain import machine_verification_recording as verification
from yoke_core.domain.handlers.machine_qa_operation import (
    TestMachineOperationResponse as OperationResponse,
)
from yoke_core.domain.machine_qa_capability import (
    replace_test_machine_settings,
    test_machine_detail as machine_detail,
)
from yoke_core.domain.machine_qa_capability_rows import (
    test_machine_capability_rows as machine_rows,
)
from runtime.api.domain.machine_qa_test_support import make_conn

MACHINE = "receipt-clock-host"
STAMP = parse_instant("1969-12-31T05:44:59.123456+05:45")
OPAQUE = {
    "name": "connection",
    "ok": True,
    "external_date": "1970-01-01",
    "external_clock": "unqualified provider evidence",
}


def seed(conn):
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings={
            "resource_name": MACHINE,
            "host": "test.example",
            "user": "tester",
            "os": "linux",
            "operating_notes": "",
        },
        base_settings=None,
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_verification_replay_keeps_native_clock_and_prior_history(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    seed(test_db)
    clock = [STAMP]
    monkeypatch.setattr(verification, "utc_now", lambda: clock[0])

    def record(lease):
        return verification.record_test_machine_verification(
            test_db,
            1,
            machine=MACHINE,
            status="verified",
            checks=[OPAQUE],
            error_code=None,
            lease_id=lease,
            contract_digest=str(lease) * 64,
        )

    first = record(11)
    assert first["checked_at"] == STAMP
    assert machine_rows(test_db, project_id=1)[0].verified_at == STAMP
    assert isinstance(machine_rows(test_db, project_id=1)[0].created_at, datetime)
    clock[0] += timedelta(microseconds=1)
    second = record(12)
    row = test_db.execute(
        "SELECT checked_at,updated_at,receipt_json FROM test_machine_verifications WHERE project_id=1 AND capability_type=%s",
        (machine_type(MACHINE),),
    ).fetchone()
    assert row[:2] == (clock[0], clock[0])
    history = json.loads(row[2])["host_control_submission_history"]
    assert history[0]["checked_at"] == "1969-12-30T23:59:59.123456Z"
    assert history[0]["checks"] == [OPAQUE]
    clock[0] += timedelta(microseconds=1)
    record(13)
    latest = test_db.execute(
        "SELECT receipt_json FROM test_machine_verifications WHERE project_id=1 AND capability_type=%s",
        (machine_type(MACHINE),),
    ).fetchone()[0]
    assert json.loads(latest)["host_control_submission_history"][0] == history[0]
    for lease, expected in [(11, first), (12, second)]:
        assert (
            verification.recorded_test_machine_verification(
                test_db,
                1,
                machine=MACHINE,
                lease_id=lease,
                contract_digest=str(lease) * 64,
            )
            == expected
        )
    assert (
        machine_detail(test_db, project="yoke", machine=MACHINE)["verification"][
            "checked_at"
        ]
        == clock[0]
    )
    assert temporal_wire(first)["checked_at"] == "1969-12-30T23:59:59.123456Z"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_operation_receipt_replay_and_order_use_native_instants(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    seed(test_db)
    clock = [STAMP]
    monkeypatch.setattr(operations, "utc_now", lambda: clock[0])
    first = operations.record_test_machine_operation(
        test_db,
        1,
        machine=MACHINE,
        operation="reset",
        status="verified",
        checks=[OPAQUE],
        error_code=None,
        lease_id=21,
        contract_digest="a" * 64,
    )
    assert first["performed_at"] == STAMP
    row = test_db.execute(
        "SELECT performed_at,updated_at,receipt_json FROM test_machine_operation_receipts WHERE project_id=1 AND capability_type=%s",
        (machine_type(MACHINE),),
    ).fetchone()
    assert row[:2] == (STAMP, STAMP)
    assert json.loads(row[2]) == {"checks": [OPAQUE]}
    assert (
        operations.recorded_test_machine_operation(
            test_db,
            1,
            machine=MACHINE,
            operation="reset",
            lease_id=21,
            contract_digest="a" * 64,
        )
        == first
    )
    clock[0] += timedelta(microseconds=1)
    operations.record_test_machine_operation(
        test_db,
        1,
        machine=MACHINE,
        operation="bridge_diagnose",
        status="error",
        checks=[],
        error_code="bridge",
        lease_id=22,
        contract_digest="b" * 64,
    )
    rows = operations.test_machine_operation_receipts(
        test_db, 1, capability_type=machine_type(MACHINE)
    )
    assert [row["performed_at"] for row in rows] == [clock[0], STAMP]


def test_sqlite_receipt_adapter_keeps_native_replay_and_canonical_storage(monkeypatch):
    conn = make_conn()
    seed(conn)
    monkeypatch.setattr(verification, "utc_now", lambda: STAMP)
    receipt = verification.record_test_machine_verification(
        conn,
        1,
        machine=MACHINE,
        status="verified",
        checks=[OPAQUE],
        error_code=None,
        lease_id=31,
        contract_digest="c" * 64,
    )
    stored = conn.execute(
        "SELECT checked_at,updated_at FROM test_machine_verifications"
    ).fetchone()
    assert tuple(stored) == ("1969-12-30T23:59:59.123456Z",) * 2
    assert (
        verification.recorded_test_machine_verification(
            conn, 1, machine=MACHINE, lease_id=31, contract_digest="c" * 64
        )
        == receipt
    )


@pytest.mark.parametrize(
    "bad", ["", "1970-01-01", "1970-01-01T00:00:00", 0, datetime(1970, 1, 1)]
)
def test_public_operation_clock_refuses_unqualified_values(bad):
    with pytest.raises(ValidationError, match="invalid_instant"):
        response(bad)


def response(clock):
    return OperationResponse(
        project="yoke",
        machine=MACHINE,
        operation="reset",
        status="verified",
        performed_at=clock,
        checks=[OPAQUE],
        error_code=None,
    )


def test_public_operation_model_keeps_native_fact_and_formats_json_or_null():
    model = response("1970-01-01T05:45:00+05:45")
    assert model.model_dump()["performed_at"] == parse_instant("1970-01-01T00:00:00Z")
    assert (
        model.model_dump(mode="json")["performed_at"] == "1970-01-01T00:00:00.000000Z"
    )
    assert response(None).model_dump(mode="json")["performed_at"] is None
