"""Executing-machine credential and failure-diagnostic coverage."""

from __future__ import annotations

import json
from typing import Any

import pytest

from yoke_cli.commands.adapters import (
    test_machine as test_machine_cli,
    test_machine_operation as operation_cli,
)
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_contracts.machine_qa_failures import (
    HostControlLocalError,
    host_control_failure,
)
from yoke_core.domain.host_control_runner import materialize_test_machine_contract


def _detail() -> dict[str, Any]:
    return {
        "project": "yoke",
        "secrets": [
            {
                "key": "ssh_private_key",
                "stored": None,
                "scope": "executing_machine",
            }
        ],
    }


def test_cli_attests_only_its_own_machine_secret_presence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        test_machine_cli,
        "list_machine_capability_secret_keys",
        lambda _project, _capability: ["ssh_private_key"],
    )
    response = FunctionCallResponse(
        success=True,
        function="test_machine.list",
        version="v1",
        result={"machines": [_detail()]},
    )

    attested = test_machine_cli._attest_secret_presence(response, "yoke")

    secret = attested.result["machines"][0]["secrets"][0]
    assert secret == {
        "key": "ssh_private_key",
        "stored": True,
        "scope": "executing_machine",
    }
    assert response.result["machines"][0]["secrets"][0]["stored"] is None


def test_missing_local_credential_has_specific_recovery(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))

    with pytest.raises(HostControlLocalError) as caught:
        materialize_test_machine_contract(
            {
                "project_id": 1,
                "project": "yoke",
                "settings": {
                    "resource_name": "mac-mini-lab",
                    "host": "test-mac.local",
                    "user": "yoke-test",
                    "host_kind": "mac-ssh",
                    "operating_notes": "",
                },
            }
        )

    assert caught.value.code == "host_control_credential_missing"
    assert caught.value.phase == "credential_materialization"
    assert "capability secret set --project yoke" in caught.value.recovery_hint


def test_operation_adapter_preserves_connection_failure_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []
    responses = [
        FunctionCallResponse(
            success=True,
            function="test_machine.operation.begin",
            version="v1",
            result={"execution": {"lease_id": 19, "contract_digest": "digest-19"}},
        ),
        FunctionCallResponse(
            success=True,
            function="test_machine.operation.abort",
            version="v1",
            result={"lease_id": 19, "released": True},
        ),
    ]

    def dispatch(**kwargs: Any) -> FunctionCallResponse:
        calls.append(dict(kwargs))
        return responses[len(calls) - 1]

    monkeypatch.setattr(operation_cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(operation_cli, "call_dispatcher", dispatch)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise HostControlLocalError(
            code="host_control_connection_failed",
            phase="host_facts_ssh",
            detail="SSH could not collect host facts",
            exit_code=255,
            stderr="Permission denied (publickey)",
            recovery_hint="Check network reachability and SSH authorization.",
        )

    monkeypatch.setattr(
        "yoke_harness.test_machine_operations.execute_host_operation_contract",
        refuse,
    )

    exit_code = test_machine_cli.test_machine_verify(["--project", "yoke", "--json"])

    assert exit_code == 1
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["error"]["code"] == "host_control_connection_failed"
    assert "phase=host_facts_ssh" in emitted["error"]["message"]
    assert "exit_code=255" in emitted["error"]["message"]
    assert "Permission denied (publickey)" in emitted["error"]["message"]
    assert "network reachability" in emitted["error"]["recovery_hint"]
    assert "ssh_private_key" not in emitted["error"]["recovery_hint"]


def test_later_execution_failure_never_echoes_untrusted_exception_text() -> None:
    code, message, recovery = host_control_failure(
        RuntimeError("top-secret runtime payload"),
        phase="reset_execution",
    )

    assert code == "host_control_local_execution_failed"
    assert "phase=reset_execution" in message
    assert "RuntimeError" in message
    assert "top-secret" not in message
    assert "repair that host operation" in recovery
