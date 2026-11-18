"""Changing a registered endpoint never silently moves an active execution."""

import json

import pytest

from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.handlers.machine_qa_execution_abort import handle_operation_abort
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import execute_host_operation_contract
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import host_claim_target


def request(function, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id="session-target-change"),
        target=TargetRef(kind="global"),
        payload={"project": "yoke", **payload},
    )


@pytest.mark.parametrize("action", ["submit", "abort"])
def test_changed_host_refuses_and_preserves_execution_custody(
    tmp_path, monkeypatch, action
):
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    seed_qa_session(conn, "session-target-change")
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handle_operation_begin(
            request("test_machine.operation.begin", {"operation": "verify"})
        )
        assert begun.primary_success, begun.error
        execution = begun.result_payload["execution"]
        submission = execute_host_operation_contract(execution)
        row = conn.execute(
            "SELECT name, settings FROM test_machines"
        ).fetchone()
        settings = json.loads(row["settings"])
        conn.execute(
            "UPDATE test_machines SET settings=? WHERE name=?",
            (
                json.dumps({**settings, "host": "replacement.example.ts.net"}),
                row["name"],
            ),
        )
        conn.commit()
        if action == "submit":
            outcome = handle_operation_submit(
                request("test_machine.operation.submit", submission.payload)
            )
        else:
            outcome = handle_operation_abort(
                request(
                    "test_machine.operation.abort",
                    {
                        "operation": "verify",
                        "lease_id": execution["lease_id"],
                        "contract_digest": execution["contract_digest"],
                        "reason": "client_cancelled",
                    },
                )
            )
        assert not outcome.primary_success
        assert "target changed after execution began" in outcome.error.message
        lease = active_claim(
            conn, host_claim_target(execution["settings"]["resource_name"])
        )
        assert lease is not None and lease.id == execution["lease_id"]
    finally:
        clear_host_control_factory()
