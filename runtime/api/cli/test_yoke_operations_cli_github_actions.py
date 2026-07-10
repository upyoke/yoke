"""Dispatch-path tests for the ``yoke github-actions`` family adapters
(``check-ci`` client-side wait loop, ``secret set``, ``variable set``)."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import List, Optional
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(
    *argv: str,
    stdin_text: Optional[str] = None,
    session_id: str = "test-session",
) -> tuple[int, str, str]:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": session_id}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=_stub_ok,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with patch("sys.stdin", io.StringIO(stdin_text or "")):
                    with redirect_stdout(io.StringIO()) as out, \
                            redirect_stderr(io.StringIO()) as err:
                        rc = cli_main(list(argv))
    return rc, out.getvalue(), err.getvalue()


class TestRegistry:
    def test_tokens_resolve_to_function_ids(self) -> None:
        from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

        assert SUBCOMMAND_REGISTRY[("github-actions", "secret", "set")][0] == (
            "github_actions.secret.set"
        )
        assert SUBCOMMAND_REGISTRY[("github-actions", "variable", "set")][0] == (
            "github_actions.variable.set"
        )


def _check_ci_response(state: str, **extra) -> dict:
    result = {"state": state, "run_id": 7, "html_url": "https://x",
              "status": None, "conclusion": None}
    result.update(extra)
    return result


class TestCheckCi:
    """Field-note 12612 — the ``--wait`` loop runs CLIENT-side: each poll
    is one single-shot ``github_actions.check_ci`` dispatch, so waiting
    works identically in-process and over the https relay. The payload
    carries no wait/timeout keys; the handler is point-in-time."""

    def _stub_states(self, states: List[str]):
        responses = iter(states)

        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result=_check_ci_response(next(responses)),
            )

        return stub

    def _run_wait(self, *argv: str, stub, clock=None):
        from yoke_cli.commands.adapters import github_actions_wait as wait_mod

        sleeps: List[float] = []
        ticks = iter(clock or [0] * 16)
        with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
            with patch(
                "yoke_core.domain.yoke_function_dispatch.dispatch",
                side_effect=stub,
            ):
                with patch(
                    "yoke_cli.commands._helpers."
                    "ensure_handlers_loaded"
                ), patch(
                    "yoke_cli.commands.adapters.github_actions_wait."
                    "ensure_handlers_loaded"
                ):
                    with patch.object(wait_mod, "now", lambda: next(ticks)), \
                            patch.object(wait_mod, "sleep", sleeps.append):
                        with redirect_stdout(io.StringIO()) as out, \
                                redirect_stderr(io.StringIO()):
                            rc = cli_main(list(argv))
        return rc, sleeps, out.getvalue()

    def test_default_payload_is_point_in_time_no_wait_keys(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "check-ci", "upyoke/yoke", "ci.yml", "--project", "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "github_actions.check_ci"
        assert req.target.kind == "global"
        assert req.payload == {
            "repo": "upyoke/yoke",
            "workflow": "ci.yml",
            "branch": "main",
            "project": "yoke",
        }

    def test_wait_polls_client_side_until_completed(self) -> None:
        from yoke_core.domain.github_actions_run_monitoring import (
            CHECK_CI_POLL_INTERVAL_SEC,
        )

        rc, sleeps, _out = self._run_wait(
            "github-actions", "check-ci", "o/r", "ci.yml", "--wait", "--project", "yoke",
            stub=self._stub_states(["running", "running", "passed"]),
            clock=[0, 10, 20],
        )
        assert rc == 0
        assert len(_CAPTURED_REQUESTS) == 3
        # Every poll is single-shot: no wait keys ever reach the wire.
        for req in _CAPTURED_REQUESTS:
            assert "wait" not in req.payload
            assert "timeout_sec" not in req.payload
        assert sleeps == [CHECK_CI_POLL_INTERVAL_SEC] * 2

    def test_wait_budget_exhaustion_synthesizes_timeout_state(self) -> None:
        rc, sleeps, out = self._run_wait(
            "github-actions", "check-ci", "o/r", "ci.yml",
            "--wait", "--timeout", "600", "--json",
            "--project", "yoke",
            stub=self._stub_states(["running", "running"]),
            clock=[0, 601],
        )
        assert rc == 0
        assert sleeps == []
        assert '"state": "timeout"' in out
        # The last-seen run info is preserved alongside the synthesized state.
        assert '"run_id": 7' in out

    def test_wait_emits_terminal_failure_response_as_is(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=True, function=request.function,
                version=request.version, request_id=request.request_id,
                result=_check_ci_response("failed", conclusion="failure"),
            )

        rc, sleeps, out = self._run_wait(
            "github-actions", "check-ci", "o/r", "ci.yml", "--wait", "--json",
            "--project", "yoke",
            stub=stub,
        )
        assert rc == 0
        assert len(_CAPTURED_REQUESTS) == 1
        assert sleeps == []
        assert '"state": "failed"' in out

    def test_wait_stops_on_dispatch_error(self) -> None:
        def stub(request: FunctionCallRequest) -> FunctionCallResponse:
            _CAPTURED_REQUESTS.append(request)
            return FunctionCallResponse(
                success=False, function=request.function,
                version=request.version, request_id=request.request_id,
                error={"code": "rest_transport_error", "message": "boom"},
            )

        rc, sleeps, _out = self._run_wait(
            "github-actions", "check-ci", "o/r", "ci.yml", "--wait", "--project", "yoke",
            stub=stub,
        )
        assert rc == 1
        assert len(_CAPTURED_REQUESTS) == 1
        assert sleeps == []

    def test_repo_without_slash_returns_two(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "check-ci", "no-slash", "ci.yml", "--wait",
            "--project", "yoke",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestSecretSet:
    def test_dispatches_with_positional_value_without_printing_it(self) -> None:
        secret = "sekret-value"

        rc, out, err = _run(
            "github-actions", "secret", "set",
            "upyoke/yoke", "YOKE_CI_TEST", secret, "--project", "yoke",
        )

        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "github_actions.secret.set"
        assert req.target.kind == "global"
        assert req.payload == {
            "repo": "upyoke/yoke",
            "name": "YOKE_CI_TEST",
            "value": secret,
            "project": "yoke",
        }
        assert secret not in out
        assert secret not in err

    def test_dispatches_with_stdin_value(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "secret", "set",
            "upyoke/yoke", "YOKE_CI_TEST", "--value-stdin",
            "--project", "yoke",
            stdin_text="sekret-value\n",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "github_actions.secret.set"
        assert req.target.kind == "global"
        assert req.payload == {
            "repo": "upyoke/yoke",
            "name": "YOKE_CI_TEST",
            "value": "sekret-value",  # trailing newline stripped
            "project": "yoke",
        }

    def test_multiline_value_preserved_minus_trailing_newline(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "secret", "set",
            "o/r", "SSH_KEY", "--value-stdin", "--project", "yoke",
            stdin_text="line-one\nline-two\n",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["value"] == "line-one\nline-two"

    def test_value_file_imports_secret(self, tmp_path) -> None:
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("file-secret\n", encoding="utf-8")

        rc, out, err = _run(
            "github-actions", "secret", "set",
            "o/r", "FILE_SECRET", "--value-file", str(secret_file), "--project", "yoke",
        )

        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["value"] == "file-secret"
        assert "file-secret" not in out
        assert "file-secret" not in err

    def test_missing_value_source_returns_two(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "secret", "set", "o/r", "NAME",
            "--project", "yoke",
            stdin_text="value",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_empty_stdin_returns_two(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "secret", "set", "o/r", "NAME", "--value-stdin",
            "--project", "yoke",
            stdin_text="",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_repo_without_slash_returns_two(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "secret", "set", "no-slash", "NAME",
            "--value-stdin", "--project", "yoke", stdin_text="v",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_value_sources_are_mutually_exclusive(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "secret", "set", "o/r", "NAME",
            "direct", "--value-stdin", "--project", "yoke",
            stdin_text="stdin",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestVariableSet:
    def test_dispatches_with_value_flag(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "variable", "set",
            "upyoke/yoke", "YOKE_PULUMI_CI_ENABLED", "--value", "false",
            "--project", "yoke",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "github_actions.variable.set"
        assert req.target.kind == "global"
        assert req.payload == {
            "repo": "upyoke/yoke",
            "name": "YOKE_PULUMI_CI_ENABLED",
            "value": "false",
            "project": "yoke",
        }

    def test_project_override(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "variable", "set",
            "o/r", "GATE", "--value", "true", "--project", "buzz",
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload["project"] == "buzz"

    def test_missing_value_returns_two(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "variable", "set", "o/r", "GATE",
            "--project", "yoke",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_repo_without_slash_returns_two(self) -> None:
        rc, _out, _err = _run(
            "github-actions", "variable", "set", "no-slash", "GATE",
            "--value", "x", "--project", "yoke",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
