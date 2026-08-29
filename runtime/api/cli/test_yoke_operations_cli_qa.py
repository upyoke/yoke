"""Dispatch-path tests for QA requirement, run, and plan commands."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result={"echo": True},
    )


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="payload_invalid", message="stub"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(stub, *argv: str, session_id: str = "test-session") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


class TestQaRequirementUpdate:
    def test_dispatches_with_value(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "update",
            "--requirement-id",
            "55",
            "--field",
            "blocking_mode",
            "--value",
            "required",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.requirement.update"
        assert req.target.kind == "qa_requirement"
        assert req.target.qa_requirement_id == 55
        assert req.payload == {"field": "blocking_mode", "value": "required"}

    def test_dispatches_with_null(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "update",
            "--requirement-id",
            "55",
            "--field",
            "skip_reason",
            "--null",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload == {"field": "skip_reason", "value": None}

    def test_missing_value_selector_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "update",
            "--requirement-id",
            "55",
            "--field",
            "blocking_mode",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_field_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "update",
            "--requirement-id",
            "55",
            "--value",
            "x",
        )
        assert rc == 2


class TestQaRequirementWaive:
    def test_dispatches_operator_force(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "waive",
            "--requirement-id",
            "55",
            "--rationale",
            "operator accepted deployment risk",
            "--source",
            "operator",
            "--force",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.requirement.waive"
        assert req.target.kind == "qa_requirement"
        assert req.target.qa_requirement_id == 55
        assert req.payload == {
            "rationale": "operator accepted deployment risk",
            "source": "operator",
            "force": True,
        }

    def test_rejects_missing_rationale(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "waive",
            "--requirement-id",
            "55",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestQaRunRecordVerdict:
    def test_dispatches_minimal(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "run",
            "record-verdict",
            "--requirement-id",
            "55",
            "--performed-by",
            "pytest",
            "--verdict",
            "pass",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.run.record_verdict"
        assert req.target.kind == "qa_requirement"
        assert req.target.qa_requirement_id == 55
        assert req.payload == {"performed_by": "pytest", "verdict": "pass"}

    def test_dispatches_with_optional_fields(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "run",
            "record-verdict",
            "--requirement-id",
            "55",
            "--performed-by",
            "pytest",
            "--verdict",
            "fail",
            "--raw-result",
            "trace...",
            "--duration-ms",
            "1200",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload == {
            "performed_by": "pytest",
            "verdict": "fail",
            "raw_result": "trace...",
            "duration_ms": 1200,
        }

    def test_missing_verdict_returns_two(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "run",
            "record-verdict",
            "--requirement-id",
            "55",
            "--performed-by",
            "pytest",
        )
        assert rc == 2

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail,
            "qa",
            "run",
            "record-verdict",
            "--requirement-id",
            "55",
            "--performed-by",
            "pytest",
            "--verdict",
            "pass",
        )
        assert rc == 1


class TestQaDeploymentPlanMaterialize:
    def test_dispatches_real_deployment_run_subject(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "plan",
            "materialize",
            "--deployment-run-id",
            "run-20260728-901",
            "--plan",
            "installer-campaign",
            "--project",
            "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.plan.materialize"
        assert req.target.kind == "deployment_run"
        assert req.target.deployment_run_id == "run-20260728-901"
        assert req.target.project_id == "yoke"
        assert req.payload == {
            "transition_id": None,
            "plan": "installer-campaign",
            "project": "yoke",
        }

    def test_requires_named_plan_and_project(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "plan",
            "materialize",
            "--deployment-run-id",
            "run-20260728-901",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestQaPlanRematerialize:
    def test_dispatches_item_snapshot_replacement(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "plan",
            "rematerialize",
            "--item",
            "YOK-1927",
            "--transition",
            "release",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.plan.rematerialize"
        assert req.target.kind == "item"
        assert req.target.public_ref == "YOK-1927"
        assert req.payload == {"transition_id": "release"}


class TestQaRequirementList:
    def test_deployment_run_filter_rides_target(self) -> None:
        rc = _run(
            _stub_ok,
            "qa",
            "requirement",
            "list",
            "--deployment-run-id",
            "run-20260731-001",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "deployment_run"
        assert req.target.deployment_run_id == "run-20260731-001"
        assert req.payload == {}
