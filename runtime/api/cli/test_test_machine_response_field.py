"""A server answer without the ``test_machine`` field refuses by name."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_cli.commands.adapters import test_machine as test_machine_cli
from yoke_cli.transport.test_machine_response_field import (
    TEST_MACHINE_RESPONSE_FIELD_MISSING,
    read_test_machine_field,
    recorded_test_machine,
)


def test_present_field_is_returned_as_served() -> None:
    assert read_test_machine_field(
        {"test_machine": "lab"}, function_id="test_machine.get"
    ) == "lab"
    assert recorded_test_machine({"recorded_path": "/r", "test_machine": None}) is None


def test_absent_field_refuses_with_reason_function_and_recovery() -> None:
    with pytest.raises(SystemExit) as refused:
        read_test_machine_field({"machine": "lab"}, function_id="test_machine.get")

    message = str(refused.value.code)
    assert message.startswith(f"error: {TEST_MACHINE_RESPONSE_FIELD_MISSING}: ")
    assert "test_machine.get returned no 'test_machine' field" in message
    assert "predates that response field" in message
    assert (
        "recovery: run the Yoke CLI release that server serves, or update the "
        "server." in message
    )


def test_artifact_answer_without_recorded_path_names_no_test_machine() -> None:
    assert recorded_test_machine({"disposition": "evidence_missing"}) is None
    with pytest.raises(SystemExit) as refused:
        recorded_test_machine({"recorded_path": "/r", "machine": "lab"})
    assert "qa.artifact.read returned no 'test_machine' field" in str(
        refused.value.code
    )


def test_list_from_a_server_without_test_machines_refuses(monkeypatch) -> None:
    monkeypatch.setattr(
        test_machine_cli, "list_machine_capability_secret_keys", lambda *_: []
    )
    response = FunctionCallResponse(
        success=True,
        function="test_machine.list",
        version="v1",
        result={"project": "yoke", "machines": []},
    )

    with pytest.raises(SystemExit) as refused:
        test_machine_cli._attest_secret_presence(response, "yoke", "test_machine.list")

    assert "test_machine.list returned no 'test_machines' field" in str(
        refused.value.code
    )
