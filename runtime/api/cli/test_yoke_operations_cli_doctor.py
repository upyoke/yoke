"""Dispatch-path tests for ``yoke doctor run``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.doctor import DOCTOR_RUN_READ_TIMEOUT_S
from yoke_cli.main import main as cli_main
from yoke_core.domain.handlers import reads_misc
from yoke_core.engines.doctor_applicability import DoctorContext, RUNTIME_LOCAL
from yoke_core.engines.doctor_project_checks import Discovery
from yoke_core.engines.doctor_registry_types import HealthCheck
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


def _handler_stub(request: FunctionCallRequest) -> FunctionCallResponse:
    outcome = reads_misc.handle_doctor_run(request)
    return FunctionCallResponse(
        success=outcome.primary_success,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=outcome.result_payload,
        warnings=outcome.warnings,
        error=outcome.error,
        event_ids=outcome.handler_event_ids,
    )


def _record_project_check(conn, args, rec) -> None:
    rec.record("HC-project-policy", "Project policy HC", "PASS", "all good")


class _Conn:
    def execute(self, *_args, **_kwargs):
        return self

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


_PROJECT_CONTEXT = DoctorContext(
    project="yoke",
    runtime=RUNTIME_LOCAL,
    self_project="yoke",
    source_checkout=Path("/target/yoke"),
)
_PROJECT_HC = HealthCheck(
    slug="project-policy",
    name="Project policy HC",
    fn=_record_project_check,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run_captured(stub, *argv: str, session_id: str = "test-session"):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with patch(
                    "yoke_cli.commands.adapters.doctor._active_transport_is_https",
                    return_value=False,
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue()


def _run(stub, *argv: str, session_id: str = "test-session") -> int:
    return _run_captured(stub, *argv, session_id=session_id)[0]


def _run_with_project_roster(checks, *argv: str):
    with (
        patch("yoke_core.engines.doctor_registry.HEALTH_CHECKS", []),
        patch("yoke_core.domain.db_helpers.connect", return_value=_Conn()),
        patch(
            "yoke_core.engines.doctor_context.resolve_context",
            return_value=_PROJECT_CONTEXT,
        ),
        patch(
            "yoke_core.engines.doctor_roster.discover_project_checks",
            return_value=Discovery(checks, []),
        ),
    ):
        return _run_captured(_handler_stub, *argv)


class TestDoctorRun:
    @pytest.mark.parametrize("json_mode", [False, True])
    def test_project_check_only_runs_in_human_and_json_modes(
        self, json_mode: bool,
    ) -> None:
        argv = ["doctor", "run", "--only", "HC-project-policy"]
        if json_mode:
            argv.append("--json")

        rc, stdout, stderr = _run_with_project_roster([_PROJECT_HC], *argv)

        assert rc == 0, stderr
        rendered = json.loads(stdout)
        result = rendered["result"] if json_mode else rendered
        assert [row["hc"] for row in result["results"]] == [
            "HC-project-policy",
        ]

    @pytest.mark.parametrize("json_mode", [False, True])
    def test_unknown_check_still_fails_after_project_roster_discovery(
        self, json_mode: bool,
    ) -> None:
        argv = ["doctor", "run", "--only", "HC-unknown-project-check"]
        if json_mode:
            argv.append("--json")

        rc, stdout, stderr = _run_with_project_roster([], *argv)

        assert rc == 1
        if json_mode:
            assert json.loads(stdout)["error"]["code"] == "invalid_check"
        else:
            assert "error (invalid_check)" in stderr

    def test_quick_dispatches(self) -> None:
        rc = _run(_stub_ok, "doctor", "run", "--quick")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "doctor.run.run"
        assert req.target.kind == "global"
        assert req.payload == {
            "project": "yoke", "quick": True, "full": False, "fix": False,
            # The client states where the checks will execute; the runner
            # would otherwise have to guess whether it can see a checkout.
            "runtime": "local",
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
                "yoke_cli.commands.adapters.doctor_https_run.call_dispatcher",
                side_effect=fake_call_dispatcher,
            ):
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    rc = cli_main(["doctor", "run", "--quick", "--json"])

        assert rc == 0
        assert len(calls) == 2
        assert calls[0]["payload"]["max_checks"] == 1
        assert calls[0]["payload"]["project_safe_quick"] is True
        assert "cursor_after" not in calls[0]["payload"]
        assert calls[1]["payload"]["cursor_after"] == "first"
        envelope = json.loads(stdout.getvalue())
        assert envelope["result"]["pass_count"] == 1
        assert envelope["result"]["warn_count"] == 1
        assert [r["hc"] for r in envelope["result"]["results"]] == [
            "HC-first", "HC-second",
        ]
