"""Fixture steps reach the candidate and keep their named, redacted reasons."""

from __future__ import annotations

import shlex

from runtime.api.domain.machine_qa_fixture_test_support import (
    FakeRemote,
    fixture_runner,
    operation,
)
from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import run_lifecycle
from yoke_core.domain.host_control_runner import HostActionResult
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
