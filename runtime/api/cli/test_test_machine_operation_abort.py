"""A retained mission lease is successful cleanup, with truthful recovery."""

import pytest

from yoke_cli.commands.adapters import test_machine_operation as adapter
from yoke_contracts.api.function_call import ActorContext, FunctionCallResponse


@pytest.mark.parametrize("released", [True, False])
def test_local_failure_reports_accepted_abort_lease_state(monkeypatch, released):
    actor = ActorContext(actor_id="2", session_id="mission-holder")
    replies = iter(
        [
            FunctionCallResponse(
                success=True,
                function="test_machine.operation.begin",
                version="v1",
                result={"execution": {"lease_id": 1, "contract_digest": "digest"}},
            ),
            FunctionCallResponse(
                success=True,
                function="test_machine.operation.abort",
                version="v1",
                result={"released": released},
            ),
        ]
    )
    monkeypatch.setattr(adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(adapter, "build_actor", lambda **kwargs: actor)
    monkeypatch.setattr(adapter, "call_dispatcher", lambda **kwargs: next(replies))
    captured = []
    monkeypatch.setattr(
        adapter,
        "emit_response",
        lambda response, **kwargs: captured.append(response) or 2,
    )

    def failed_execution(*args, **kwargs):
        raise ValueError("capture unavailable")

    monkeypatch.setattr(
        "yoke_harness.test_machine_operations.execute_host_operation_contract",
        failed_execution,
    )
    assert (
        adapter._execute(
            operation="screenshot",
            project="example",
            machine=None,
            baseline=None,
            destination=None,
            capture_component=None,
            probes_document=None,
            session_id=None,
            json_mode=True,
        )
        == 2
    )
    error = captured[0].error
    assert (
        "server lease was released" if released else "mission host lease was retained"
    ) in error.message
    assert "also failed" not in error.message
    assert "release the named coordination lease" not in error.recovery_hint
