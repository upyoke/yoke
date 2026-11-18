"""The tailnet power proof calls the live CLI with argv it accepts."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runtime.api.tools import test_machine_tailnet_power_proof as proof
from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
)

HOST = "linux-lab.tail1234.ts.net"
RECORD = {
    "test_machine": "linux-lab",
    "settings": {"host": HOST, "cloud_instance_id": "i-0abc"},
}


def _served_request(argv: list[str]) -> FunctionCallRequest:
    """Parse argv with the real CLI and return the request it dispatched."""
    captured: list[FunctionCallRequest] = []

    def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
        captured.append(request)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={},
        )

    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=dispatch,
        ):
            with patch("yoke_cli.commands._helpers.ensure_handlers_loaded"):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    cli_main(argv)
    assert captured, f"CLI refused helper argv before dispatch: {argv}"
    return captured[0]


def _fake_cli(
    calls: list[list[str]],
    verify_output: str = "verified\n",
    leases: tuple[dict | None, dict | None] = (None, None),
):
    records = [{**RECORD, "active_lease": lease} for lease in leases]

    def run(cmd, **_kwargs):
        argv = cmd[1:]
        calls.append(argv)
        stdout = ""
        if argv[0] == "test-machine":
            request = _served_request(argv)
            assert request.payload.get("test_machine") == "linux-lab"
            if argv[1] == "get":
                stdout = json.dumps({"success": True, "result": records.pop(0)})
            elif argv[1] == "verify":
                stdout = verify_output
        else:
            assert argv[:4] == ["aws", "exec", "--project", "yoke"]
            stdout = json.dumps("running")
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    return run


def _main(monkeypatch: pytest.MonkeyPatch, run) -> None:
    # Replace only the helper's subprocess binding; the CLI keeps the real one.
    monkeypatch.setattr(
        proof,
        "subprocess",
        SimpleNamespace(
            run=run,
            CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["proof", "--project", "yoke", "--test-machine", "linux-lab"],
    )
    proof.main()


def test_test_machine_calls_parse_and_cloud_reads_keep_project(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []
    _main(monkeypatch, _fake_cli(calls))

    machine_calls = [argv[:2] for argv in calls if argv[0] == "test-machine"]
    assert machine_calls == [
        ["test-machine", "get"],
        ["test-machine", "exec"],
        ["test-machine", "verify"],
        ["test-machine", "get"],
    ]
    assert all(
        "--project" not in argv for argv in calls if argv[0] == "test-machine"
    )
    assert f"PASS linux-lab: host unchanged ({HOST})" in capsys.readouterr().out


def test_reported_provider_stop_still_fails_the_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    with pytest.raises(RuntimeError, match="tailnet_power_failed"):
        _main(monkeypatch, _fake_cli(calls, "Stopping instance i-0abc\n"))


def test_runner_held_lease_is_borrowed_and_must_stay_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner_lease = {"id": 51767}
    _main(monkeypatch, _fake_cli([], leases=(runner_lease, runner_lease)))
    assert "host lease unchanged" in capsys.readouterr().out


@pytest.mark.parametrize(
    "leases",
    [(None, {"id": 9}), ({"id": 51767}, {"id": 9}), ({"id": 51767}, None)],
)
def test_lease_left_different_by_exec_or_verify_fails_the_proof(
    monkeypatch: pytest.MonkeyPatch, leases
) -> None:
    with pytest.raises(RuntimeError, match="different host lease"):
        _main(monkeypatch, _fake_cli([], leases=leases))
