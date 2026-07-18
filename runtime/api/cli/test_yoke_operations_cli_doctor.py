"""Dispatch-path tests for ``yoke doctor run``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.doctor import DOCTOR_RUN_READ_TIMEOUT_S
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
        success=True, function=request.function, version=request.version,
        request_id=request.request_id,
        result={"results": [], "scope": "quick", "project": "yoke",
                "fail_count": 0, "warn_count": 0, "pass_count": 0},
    )


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False, function=request.function, version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="invalid_payload", message="stub"),
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
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return cli_main(list(argv))


class TestDoctorRun:
    def test_quick_dispatches(self) -> None:
        rc = _run(_stub_ok, "doctor", "run", "--quick")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "doctor.run.run"
        assert req.target.kind == "global"
        assert req.payload == {
            "project": "yoke", "quick": True, "full": False, "fix": False,
        }

    def test_full_with_fix(self) -> None:
        rc = _run(_stub_ok, "doctor", "run", "--full", "--fix")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["full"] is True
        assert req.payload["fix"] is True

    def test_only_with_project_override(self) -> None:
        rc = _run(
            _stub_ok, "doctor", "run",
            "--only", "HC-foo,HC-bar", "--project", "externalwebapp",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.payload["only"] == "HC-foo,HC-bar"
        assert req.payload["project"] == "externalwebapp"

    def test_missing_scope_returns_two(self) -> None:
        rc = _run(_stub_ok, "doctor", "run")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_multiple_scopes_returns_two(self) -> None:
        rc = _run(_stub_ok, "doctor", "run", "--quick", "--full")
        assert rc == 2

    def test_dispatch_failure_propagates_exit_one(self) -> None:
        rc = _run(_stub_fail, "doctor", "run", "--quick")
        assert rc == 1

    def test_dispatch_uses_doctor_read_timeout(self) -> None:
        calls = {}

        def fake_dispatch_and_emit(**kwargs):
            calls.update(kwargs)
            return 0

        with patch(
            "yoke_cli.commands.adapters.doctor.dispatch_and_emit",
            side_effect=fake_dispatch_and_emit,
        ):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = cli_main(["doctor", "run", "--quick"])

        assert rc == 0
        assert calls["timeout_s"] == DOCTOR_RUN_READ_TIMEOUT_S

    def test_https_dispatch_chunks_and_aggregates(self) -> None:
        calls = []

        def fake_call_dispatcher(**kwargs):
            calls.append(kwargs)
            request_id = f"req-{len(calls)}"
            if len(calls) == 1:
                return FunctionCallResponse(
                    success=True,
                    function="doctor.run.run",
                    version="v1",
                    request_id=request_id,
                    result={
                        "results": [
                            {
                                "hc": "HC-first",
                                "name": "First",
                                "severity": "PASS",
                                "detail": "",
                            }
                        ],
                        "scope": "quick",
                        "project": "yoke",
                        "fail_count": 0,
                        "warn_count": 0,
                        "pass_count": 1,
                        "done": False,
                        "cursor": "first",
                    },
                )
            return FunctionCallResponse(
                success=True,
                function="doctor.run.run",
                version="v1",
                request_id=request_id,
                result={
                    "results": [
                        {
                            "hc": "HC-second",
                            "name": "Second",
                            "severity": "WARN",
                            "detail": "note",
                        }
                    ],
                    "scope": "quick",
                    "project": "yoke",
                    "fail_count": 0,
                    "warn_count": 1,
                    "pass_count": 0,
                    "done": True,
                    "cursor": "second",
                },
            )

        stdout = io.StringIO()
        with patch(
            "yoke_cli.commands.adapters.doctor._active_transport_is_https",
            return_value=True,
        ):
            with patch(
                "yoke_cli.commands.adapters.doctor.call_dispatcher",
                side_effect=fake_call_dispatcher,
            ):
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    rc = cli_main(["doctor", "run", "--quick", "--json"])

        assert rc == 0
        assert len(calls) == 2
        assert calls[0]["payload"]["max_checks"] == 1
        assert calls[0]["payload"]["skip_source_tree_checks"] is True
        assert "cursor_after" not in calls[0]["payload"]
        assert calls[1]["payload"]["cursor_after"] == "first"
        envelope = json.loads(stdout.getvalue())
        assert envelope["result"]["pass_count"] == 1
        assert envelope["result"]["warn_count"] == 1
        assert [r["hc"] for r in envelope["result"]["results"]] == [
            "HC-first", "HC-second",
        ]
