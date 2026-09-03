"""Cleanup coverage for rejected Test Mac verification submissions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yoke_cli.commands.adapters import (
    test_machine as test_machine_cli,
    test_machine_operation as test_machine_operation_cli,
)
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_harness.test_machine_operations import (
    LocalHostControlSubmission,
)


def test_verify_cli_cleans_local_artifacts_after_rejected_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = tmp_path / "verification-capture.txt"
    artifact.write_text("secret-free capture", encoding="utf-8")
    responses = [
        FunctionCallResponse(
            success=True,
            function="test_machine.operation.begin",
            version="v1",
            result={
                "execution": {
                    "lease_id": 23,
                    "contract_digest": "digest-23",
                },
            },
        ),
        FunctionCallResponse(
            success=False,
            function="test_machine.operation.submit",
            version="v1",
            error=FunctionError(
                code="submission_rejected",
                message="submission rejected",
            ),
        ),
        FunctionCallResponse(
            success=True,
            function="test_machine.operation.abort",
            version="v1",
            result={"lease_id": 23, "released": True},
        ),
    ]
    calls: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> FunctionCallResponse:
        calls.append(dict(kwargs))
        return responses[len(calls) - 1]

    monkeypatch.setattr(
        test_machine_operation_cli,
        "ensure_handlers_loaded",
        lambda: None,
    )
    monkeypatch.setattr(test_machine_operation_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        "yoke_harness.test_machine_operations.execute_host_operation_contract",
        lambda _contract, **_kwargs: LocalHostControlSubmission(
            payload={
                "lease_id": 23,
                "contract_digest": "digest-23",
                "operation": "verify",
                "status": "verified",
                "checks": [],
                "error_code": None,
            },
            artifact_paths=(artifact,),
        ),
    )

    exit_code = test_machine_cli.test_machine_verify(["--project", "yoke", "--json"])

    assert exit_code == 1
    assert not artifact.exists()
    assert [call["function_id"] for call in calls] == [
        "test_machine.operation.begin",
        "test_machine.operation.submit",
        "test_machine.operation.abort",
    ]
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "submission_rejected"
    )
