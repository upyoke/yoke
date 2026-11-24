"""A reset or verify by the holder of a reserved plan host turn keeps that turn.

Measured miss: lease 51966 on windows-native-lab was reserved for its holder's
plan execution; the holder's ``yoke test-machine reset`` consumed the turn and
its submit released the host to the next waiter 4ms later (feedback 97614).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.machine_operation_test_support import (
    MACHINE as CONFIGURED_MACHINE,
)
from runtime.api.domain.machine_screenshot_test_support import screenshot_result
from runtime.api.domain.qa_host_turns_test_support import (
    MACHINE,
    _execution_wait,
    _notices,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import machine_qa_execution_protocol as protocol
from yoke_core.domain import machine_qa_operation_lease as operations
from yoke_core.domain import qa_plan_abort_reset
from yoke_core.domain.coordination_claims import (
    acquire,
    active_claim,
    get_claim,
    release,
)
from yoke_core.domain.handlers.machine_qa_execution_abort import _release_operation
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import execute_host_operation_contract
from yoke_core.domain.qa_host_holdover import DIRECT_OPERATION_REASON, HOLDOVER_REASON
from yoke_core.domain.qa_host_turns import HOST_TURN_REASON
from yoke_core.domain.work_claim_targets import make_qa_admission_target

TARGET = make_qa_admission_target(MACHINE)
HOLDER = ActorContext(actor_id="1", session_id="holder")
RESET = {"operation": "reset", "checks": (), "baselines": ("clean",)}


@pytest.fixture
def stubbed_host(monkeypatch):
    """Stand the lab's contract in for the project's declared Test Machine."""
    contract = SimpleNamespace(settings={"resource_name": MACHINE})
    loader = lambda *_, **__: contract  # noqa: E731
    monkeypatch.setattr(operations, "load_test_machine_contract", loader)
    monkeypatch.setattr(protocol, "load_test_machine_contract", loader)
    issued = []

    def issue(conn, candidate, lease, **shape):
        issued.append(lease.id)
        return SimpleNamespace(lease_id=lease.id, contract_digest="digest")

    monkeypatch.setattr(operations, "_issue", issue)

    def admit(conn, *, session_id, **_shape):
        lease = acquire(conn, TARGET, session_id, reason="machine-qa-execution")
        issued.append(lease.id)
        return SimpleNamespace(lease_id=lease.id, contract_digest="digest")

    monkeypatch.setattr(operations, "begin_host_control_execution", admit)
    return issued


def _waits(conn, session_id):
    return [
        (row["state"], row["qa_plan_execution_id"])
        for row in conn.execute(
            "SELECT state,qa_plan_execution_id FROM qa_test_machine_waits "
            "WHERE session_id=%s ORDER BY queued_at,id",
            (session_id,),
        ).fetchall()
    ]


def _reserved_plan_turn(conn, monkeypatch, *, machine=MACHINE):
    """Holder's plan execution is reserved the host; another plan waits behind."""
    seed_qa_session(conn, "owner", "holder", "behind")
    _notices(monkeypatch)
    target = make_qa_admission_target(machine)
    first = acquire(conn, target, "owner")
    execution = _execution_wait(conn, "holder", machine)
    release(conn, first.id, "complete")
    turn = active_claim(conn, target)
    assert turn.session_id == "holder"
    assert turn.reason.startswith(HOST_TURN_REASON)
    behind = _execution_wait(conn, "behind", machine)
    return turn, execution, behind


def _begin(conn):
    return operations.begin_operation_execution(
        conn, actor=HOLDER, project="yoke", test_machine=MACHINE, **RESET
    )


def _assert_turn_kept(conn, turn, execution, behind):
    kept = get_claim(conn, turn.id)
    assert kept.is_active and kept.reason == turn.reason
    assert _waits(conn, "holder") == [("reserved", execution)]
    assert _waits(conn, "behind") == [("waiting", behind)]
    state = conn.execute(
        "SELECT state FROM qa_plan_executions WHERE id=%s", (execution,)
    ).fetchone()["state"]
    assert state == "waiting"


def test_reset_on_a_reserved_plan_turn_keeps_it_for_the_plan_run(
    test_db, monkeypatch, stubbed_host
):
    turn, execution, behind = _reserved_plan_turn(test_db, monkeypatch)

    contract = _begin(test_db)
    assert contract.lease_id == turn.id
    assert get_claim(test_db, turn.id).reason == turn.reason + ":operation:digest"

    lease = get_claim(test_db, turn.id)
    released = operations.finish_operation_execution(
        test_db,
        lease,
        mission=None,
        reason="test-machine-reset-complete",
        contract_digest="digest",
    )
    assert released is False
    _assert_turn_kept(test_db, turn, execution, behind)

    # The plan's own run then consumes the turn it kept.
    run = acquire(test_db, TARGET, "holder", reason="machine-qa-execution")
    assert run.id == turn.id
    assert _waits(test_db, "holder") == [("granted", execution)]
    assert _waits(test_db, "behind") == [("waiting", behind)]


def test_aborted_reset_on_a_reserved_plan_turn_keeps_it(
    test_db, monkeypatch, stubbed_host
):
    turn, execution, behind = _reserved_plan_turn(test_db, monkeypatch)
    _begin(test_db)
    monkeypatch.setattr(
        qa_plan_abort_reset,
        "validate_operation_submission",
        lambda conn, *, lease_id, **_: (get_claim(conn, lease_id), None),
    )

    result = _release_operation(
        test_db,
        request=FunctionCallRequest(
            function="machine_qa.operation.abort",
            actor=HOLDER,
            target=TargetRef(kind="global"),
        ),
        project="yoke",
        lease_id=turn.id,
        contract_digest="digest",
        reason="local_execution_failed",
        operation="reset",
        baselines=("clean",),
    )

    assert result["released"] is False
    _assert_turn_kept(test_db, turn, execution, behind)


def test_reset_on_a_holdover_still_consumes_and_releases_it(
    test_db, monkeypatch, stubbed_host
):
    seed_qa_session(test_db, "holder", "behind")
    _notices(monkeypatch)
    preflight = acquire(test_db, TARGET, "holder", reason=DIRECT_OPERATION_REASON)
    release(test_db, preflight.id, "finished: test-machine exec")
    test_db.commit()
    holdover = active_claim(test_db, TARGET)
    assert holdover.reason == HOLDOVER_REASON

    contract = _begin(test_db)
    lease = get_claim(test_db, contract.lease_id)
    assert lease.id == holdover.id and lease.reason == "machine-qa-execution"
    released = operations.finish_operation_execution(
        test_db,
        lease,
        mission=None,
        reason="test-machine-reset-complete",
        contract_digest="digest",
    )

    assert released is True
    assert not get_claim(test_db, holdover.id).is_active


def _operation_request(function, payload):
    return FunctionCallRequest(
        function=f"test_machine.operation.{function}",
        actor=HOLDER,
        target=TargetRef(kind="global"),
        payload={"project": "yoke", **payload},
    )


@pytest.mark.parametrize(
    ("operation", "table"),
    [
        ("reset", "test_machine_operation_receipts"),
        ("verify", "test_machine_verifications"),
        ("screenshot", "test_machine_operation_receipts"),
    ],
)
def test_changed_result_replaces_receipt_on_reserved_plan_turn(
    test_db, tmp_path, monkeypatch, operation, table
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    turn, execution, behind = _reserved_plan_turn(
        test_db, monkeypatch, machine=CONFIGURED_MACHINE
    )

    def begin():
        begun = handle_operation_begin(
            _operation_request(
                "begin", {"test_machine": CONFIGURED_MACHINE, "operation": operation}
            )
        )
        assert begun.primary_success, begun.error
        contract = begun.result_payload["execution"]
        assert contract["lease_id"] == turn.id
        return contract

    def submit(payload):
        result = handle_operation_submit(_operation_request("submit", payload))
        assert result.primary_success, result.error
        _assert_turn_kept(test_db, turn, execution, behind)
        return result.result_payload

    uploads = []

    def store(conn, *, filename, **kwargs):
        uploads.append(filename)
        return {
            "backend": "local",
            "path": str(tmp_path / filename),
            "content_type": "image/png",
        }

    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_screenshot_artifact.store_owned_artifact_bytes",
        store,
    )

    def rows():
        result = test_db.execute(
            f"SELECT xmin, * FROM {table} WHERE test_machine_id="
            "(SELECT id FROM test_machines WHERE name=%s)",
            (CONFIGURED_MACHINE,),
        ).fetchall()
        return [dict(row) for row in result]

    first = begin()
    failed_check = {
        "reset": first["baselines"],
        "verify": first["checks"],
        "screenshot": ["screenshot"],
    }[operation][0]
    failed = submit(
        {
            "operation": operation,
            "lease_id": turn.id,
            "contract_digest": first["contract_digest"],
            "status": "error",
            "error_code": "host_operation_failed",
            "checks": [{"name": failed_check, "ok": False}],
        }
    )
    assert failed["status"] == "error"
    [failed_row] = rows()
    assert failed_row["status"] == "error"

    second = begin()
    assert second["contract_digest"] == first["contract_digest"]
    control = FakeHostControl()
    control.capture_screenshot = screenshot_result
    register_host_control_factory(lambda _: control)
    try:
        payload = execute_host_operation_contract(second).payload
    finally:
        clear_host_control_factory()
    accepted = submit(payload)
    assert accepted["status"] == "verified"
    [accepted_row] = rows()
    assert accepted_row["status"] == "verified"
    assert submit(payload) == accepted
    assert rows() == [accepted_row]
    if operation == "verify":
        assert not json.loads(accepted_row["receipt_json"]).get(
            "host_control_submission_history"
        )
    if operation == "screenshot":
        assert uploads == [f"desktop-{accepted['checks'][0]['sha256']}.png"]
