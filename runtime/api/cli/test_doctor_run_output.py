"""``yoke doctor run`` output contract: streaming, report, exit status.

The command is what ``yoke watch doctor`` runs on every machine, so its
progress lines, its rendered report, and its exit status have to hold on
both transports — a relayed control plane has no local database for the
engine entrypoint to open, and that is exactly where an operator most
needs to see a long run making progress.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


def _response(
    rows: List[Dict[str, Any]],
    *,
    fail_count: int = 0,
    warn_count: int = 0,
    pass_count: int = 0,
    done: bool = True,
    cursor: str | None = None,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="doctor.run.run",
        version="v1",
        request_id="req-1",
        result={
            "results": rows,
            "scope": "quick",
            "project": "yoke",
            "runtime": "local",
            "fail_count": fail_count,
            "warn_count": warn_count,
            "pass_count": pass_count,
            "na_count": 0,
            "done": done,
            "cursor": cursor,
        },
    )


_PASS_ROW = {"hc": "HC-one", "name": "First", "severity": "PASS", "detail": ""}
_FAIL_ROW = {"hc": "HC-two", "name": "Second", "severity": "FAIL", "detail": "broke"}


def _run_local(response, *argv: str):
    """Invoke the CLI over a non-https connection."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
        patch(
            "yoke_cli.commands.adapters.doctor._active_transport_is_https",
            return_value=False,
        ),
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch(
            "yoke_cli.commands.adapters.doctor.ensure_handlers_loaded"
        ),
        patch(
            "yoke_cli.commands.adapters.doctor.call_dispatcher",
            side_effect=response,
        ),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        rc = cli_main(list(argv))
    return rc, stdout.getvalue(), stderr.getvalue()


class TestInProcessRunStreams:
    def test_handler_progress_reaches_stderr(self) -> None:
        # The in-process dispatch runs the handler's check loop inside the
        # caller's sink, so a verdict emitted mid-run is visible mid-run.
        def dispatching(**kwargs):
            progress = __import__(
                "yoke_core.engines.doctor_progress", fromlist=["check_started"]
            )
            progress.check_started("one")
            progress.check_finished("HC-one", "PASS")
            return _response([_PASS_ROW], pass_count=1)

        rc, stdout, stderr = _run_local(dispatching, "doctor", "run", "--quick")

        assert rc == 0
        assert "running HC-one" in stderr
        assert "HC-one: PASS" in stderr
        # stdout stays the report a caller reads or parses.
        assert "running HC-one" not in stdout


class TestHumanReport:
    def test_human_mode_renders_the_health_report(self) -> None:
        rc, stdout, _ = _run_local(
            lambda **_: _response([_PASS_ROW], pass_count=1),
            "doctor", "run", "--quick",
        )
        assert rc == 0
        assert stdout.startswith("# Ouroboros Health Report")
        assert "HC-one: First" in stdout

    def test_json_mode_still_emits_the_envelope(self) -> None:
        rc, stdout, _ = _run_local(
            lambda **_: _response([_PASS_ROW], pass_count=1),
            "doctor", "run", "--quick", "--json",
        )
        assert rc == 0
        envelope = json.loads(stdout)
        assert envelope["result"]["results"][0]["hc"] == "HC-one"

    def test_file_flag_writes_the_report(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "health.md"
        rc, stdout, _ = _run_local(
            lambda **_: _response([_PASS_ROW], pass_count=1),
            "doctor", "run", "--quick", "--file", str(target),
        )
        assert rc == 0
        assert target.read_text().startswith("# Ouroboros Health Report")
        assert f"Report saved to: {target}" in stdout


class TestExitStatus:
    def test_clean_run_exits_zero(self) -> None:
        rc, _, _ = _run_local(
            lambda **_: _response([_PASS_ROW], pass_count=1),
            "doctor", "run", "--quick",
        )
        assert rc == 0

    def test_recorded_failure_exits_one(self) -> None:
        # Callers branch on this status to decide "is this install healthy?".
        rc, stdout, _ = _run_local(
            lambda **_: _response([_FAIL_ROW], fail_count=1),
            "doctor", "run", "--quick",
        )
        assert rc == 1
        assert "## Failures" in stdout

    def test_dispatch_error_exits_one_and_teaches(self) -> None:
        failed = FunctionCallResponse(
            success=False,
            function="doctor.run.run",
            version="v1",
            request_id="req-1",
            error=FunctionError(
                code="invalid_check", message="unknown HC slug(s): HC-nope"
            ),
        )
        rc, _, stderr = _run_local(
            lambda **_: failed, "doctor", "run", "--only", "HC-nope",
        )
        assert rc == 1
        assert "error (invalid_check)" in stderr


class TestRelayedRunStreams:
    def _run_https(self, *argv: str):
        batches = [
            _response([_PASS_ROW], pass_count=1, done=False, cursor="one"),
            _response([_FAIL_ROW], fail_count=1, done=True, cursor="two"),
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}),
            patch(
                "yoke_cli.commands.adapters.doctor._active_transport_is_https",
                return_value=True,
            ),
            patch(
                "yoke_cli.commands.adapters.doctor_https_compose."
                "resolve_operator_project",
                return_value="yoke",
            ),
            patch(
                "yoke_cli.commands.adapters.doctor_https_compose."
                "machine_has_checkout_for",
                return_value=False,
            ),
            patch(
                "yoke_cli.commands.adapters.doctor_https_receipt."
                "persist_composed_receipt",
            ),
            patch(
                "yoke_cli.commands.adapters.doctor_https_run.call_dispatcher",
                side_effect=lambda **_: batches.pop(0),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            rc = cli_main(list(argv))
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_each_relayed_batch_emits_its_verdict(self) -> None:
        rc, stdout, stderr = self._run_https("doctor", "run", "--quick")

        # One bounded batch per check, so each response is a progress tick.
        assert "HC-one: PASS" in stderr
        assert "HC-two: FAIL" in stderr
        assert stdout.startswith("# Ouroboros Health Report")
        assert rc == 1  # the run recorded a FAIL

    def test_relayed_run_reports_both_verdicts_in_one_report(self) -> None:
        _, stdout, _ = self._run_https("doctor", "run", "--quick")
        assert "## Failures" in stdout
        assert "## Passed" in stdout


@pytest.mark.parametrize("argv", [["doctor", "run"], ["doctor", "run", "--quick", "--full"]])
def test_scope_is_still_required(argv: list[str]) -> None:
    rc, _, _ = _run_local(lambda **_: _response([]), *argv)
    assert rc == 2
