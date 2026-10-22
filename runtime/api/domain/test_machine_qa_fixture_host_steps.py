"""Fixture steps reach the candidate and keep their named, redacted reasons."""

from __future__ import annotations

from pathlib import Path
import shlex
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_fixture_test_support import (
    FakeRemote,
    fixture_runner,
    operation,
)
from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
    action_result,
    run_lifecycle,
)
from yoke_core.domain import machine_qa_admission_host as admission_host
from yoke_core.domain.host_control_runner import HostActionResult
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.machine_qa_fixture_admission import HOST_MODULE
from yoke_core.domain.machine_qa_fixture_runtime import (
    MachineQaFixtureRuntime,
    RemoteFixtureFailure,
    ServiceCleanup,
)


def test_failed_operations_keep_their_redacted_reason() -> None:
    failed = HostActionResult(
        ok=False,
        evidence={
            "operations": [
                {
                    "id": "fixture.machine-admission-prepare",
                    "outcome": "failed",
                    "reason": "machine_admission_server_exited: token tok-123\nlog",
                }
            ]
        },
    )
    result, _execution, _events = run_lifecycle(
        setup=failed, cleanup=[failed, failed], secrets={"token": "tok-123"}
    )

    reason = "machine_admission_server_exited: token [REDACTED] log"
    operations = result.evidence["fixture_operations"]
    assert operations["setup"]["operations"][-1]["reason"] == reason
    assert [
        attempt["operations"][0]["reason"]
        for attempt in operations["cleanup_attempts"]
    ] == [reason, reason]


def test_runtime_close_keeps_the_cleanup_failure_reason() -> None:
    runtime = MachineQaFixtureRuntime(
        run_remote=lambda *_a, **_kw: None, upload_text=lambda *_a: None,
        home="/Users/testy",
    )

    def refuse() -> None:
        raise RemoteFixtureFailure("machine_admission_host_failed: exit 1")

    runtime._services["machine-admission:self-hosted"] = ServiceCleanup(
        "fixture.machine-admission-prepare", refuse
    )
    assert runtime.close().evidence["operations"] == [
        {
            "id": "fixture.machine-admission-prepare",
            "outcome": "failed",
            "reason": "machine_admission_host_failed: exit 1",
        }
    ]


def test_admission_host_runs_on_the_current_release_interpreter() -> None:
    remote = FakeRemote()
    runner = fixture_runner(remote)

    result = runner.execute_setup_operations(
        [operation("fixture.machine-admission-prepare", mode="self-hosted")]
    )
    runner.close()

    assert result.ok, result.evidence
    release_python = (
        "/Users/tester/.local/share/uv/tools/yoke-cli-releases/current/"
        "tools/yoke-cli/bin/python3"
    )
    assert [shlex.split(command) for command, _timeout in remote.commands] == [
        [release_python, "-m", HOST_MODULE, "stop" if step else "start", "self-hosted"]
        for step in (False, True)
    ]


def test_a_failed_journey_reports_its_own_error_before_the_state_proof() -> None:
    journey = MachineCaseResult(
        case_outcome="failed",
        verdict="fail",
        evidence={"steps": [{"key": "invite-code"}]},
        error_code="terminal_ready_timeout",
    )
    result, _execution, events = run_lifecycle(
        primary=journey,
        post_state=action_result(False, "fixture.machine-admission-state-assert"),
    )

    assert events == ["setup", "primary", "post-state", "close"]
    assert result.error_code == "terminal_ready_timeout"
    assert result.evidence["steps"] == [{"key": "invite-code"}]
    post_state = result.evidence["fixture_operations"]["post_state"]
    assert post_state["outcome"] == "failed"


def test_a_crashed_host_step_reports_its_exception_not_the_traceback_header() -> None:
    remote = FakeRemote()
    remote.stdout = "\n".join((
        "host warning before traceback",
        "Traceback (most recent call last):",
        '  File "' + "long-path" * 100 + '", line 1, in stop',
        "PermissionError: [Errno 1] Operation not permitted",
    ))
    remote.fail_once_contains = "machine_qa_admission_host start"
    runner = fixture_runner(remote)

    result = runner.execute_setup_operations(
        [operation("fixture.machine-admission-prepare", mode="self-hosted")]
    )
    runner.close()

    reason = result.evidence["operations"][0]["reason"]
    assert reason.endswith("PermissionError: [Errno 1] Operation not permitted")
    assert len(reason) <= 512
    case, _execution, _events = run_lifecycle(setup=result)
    assert case.evidence["fixture_operations"]["setup"]["operations"][0]["reason"] == reason


def test_stop_treats_an_exited_process_group_as_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "self-hosted"
    root.mkdir()
    (root / "identity.json").write_text('{"pid": 4242}\n', encoding="utf-8")
    monkeypatch.setattr(admission_host, "mode_root", lambda _mode: root)
    monkeypatch.setattr(
        admission_host,
        "universe_spec",
        lambda _mode: SimpleNamespace(bin_dir=None, data_dir=root / "universe"),
    )

    def exited_group(pid: int, sig: int) -> None:
        assert sig != admission_host.signal.SIGKILL
        if sig == 0:
            raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(admission_host.os, "killpg", exited_group)
    admission_host.stop("self-hosted")
    assert not root.exists()


def test_cleanup_retry_removes_root_and_preserves_first_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
        FakeFixtureRunner,
    )

    root = tmp_path / "self-hosted"
    root.mkdir()
    (root / "identity.json").write_text('{"pid": 4242}\n', encoding="utf-8")
    monkeypatch.setattr(admission_host, "mode_root", lambda _mode: root)
    monkeypatch.setattr(
        admission_host, "universe_spec",
        lambda _mode: SimpleNamespace(bin_dir=None, data_dir=root / "universe"),
    )
    calls = []

    def exiting_group(pid: int, sig: int) -> None:
        calls.append(sig)
        if len(calls) == 1:
            raise PermissionError(1, "Operation not permitted")
        if sig == 0:
            raise ProcessLookupError()

    monkeypatch.setattr(admission_host.os, "killpg", exiting_group)
    runtime = MachineQaFixtureRuntime(
        run_remote=lambda *_a, **_kw: None, upload_text=lambda *_a: None,
        home="/Users/testy",
    )

    def stop() -> None:
        try:
            admission_host.stop("self-hosted")
        except admission_host.AdmissionFixtureError as exc:
            assert root.exists()
            raise RemoteFixtureFailure(str(exc)) from exc

    runtime._services["machine-admission:self-hosted"] = ServiceCleanup(
        "fixture.machine-admission-prepare", stop
    )
    monkeypatch.setattr(FakeFixtureRunner, "close", lambda _self: runtime.close())
    result, _execution, _events = run_lifecycle()

    assert result.case_outcome == "passed"
    assert not root.exists()
    attempts = result.evidence["fixture_operations"]["cleanup_attempts"]
    assert [attempt["outcome"] for attempt in attempts] == ["failed", "passed"]
    assert "PermissionError: [Errno 1]" in attempts[0]["operations"][0]["reason"]


def test_cleanup_fails_when_fixture_root_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "local"
    root.mkdir()
    monkeypatch.setattr(admission_host, "mode_root", lambda _mode: root)
    monkeypatch.setattr(
        admission_host, "universe_spec",
        lambda _mode: SimpleNamespace(bin_dir=None, data_dir=root / "universe"),
    )
    monkeypatch.setattr(admission_host.shutil, "rmtree", lambda *_a, **_kw: None)

    with pytest.raises(admission_host.AdmissionFixtureError, match="remains"):
        admission_host.stop("local")
