"""A server answer without the ``test_machine`` field refuses by name."""

from __future__ import annotations

import io

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


def test_list_from_a_server_without_test_machines_refuses() -> None:
    response = FunctionCallResponse(
        success=True,
        function="test_machine.list",
        version="v1",
        result={"project": "yoke", "machines": []},
    )

    with pytest.raises(SystemExit) as refused:
        test_machine_cli._attest_secret_presence(response, "test_machine.list")

    assert "test_machine.list returned no 'test_machines' field" in str(
        refused.value.code
    )



def test_human_fleet_listing_fits_without_serializing_receipts() -> None:
    machines = [
        {
            "test_machine": name,
            "os": "linux",
            "power_project": "cloud-team",
            "active_lease": None,
            "verification": {"status": "verified", "checks": ["evidence" * 4000]},
        }
        for name in ("build", "install", "desktop", "terminal")
    ]
    response = FunctionCallResponse(
        success=True, function="test_machine.list", version="v1",
        result={"test_machines": machines},
    )
    output = io.StringIO()
    test_machine_cli._write_fleet(response, output, io.StringIO())
    assert output.getvalue().splitlines() == [
        "Test Machine\tOS\tPower project\tState",
        *[f"{row['test_machine']}\tlinux\tcloud-team\tverified" for row in machines],
    ]
