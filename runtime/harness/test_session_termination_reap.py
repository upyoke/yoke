"""Machine-relay process reaping for permanently terminated sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    release_supervised_native,
)
from yoke_harness.session_relay_runtime import run_registered_job
from yoke_harness.session_relay_termination import (
    NATIVE_HANDLE_DIRECTORY_NAME,
    adopt_launched_session,
    reap_terminated_session,
    stop_claude_job,
)


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
NATIVE_ID = "33333333-3333-4333-8333-333333333333"


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _handle_path(state_dir: Path) -> Path:
    return state_dir / NATIVE_HANDLE_DIRECTORY_NAME / f"{LAUNCH_ID}.json"


def _job(**values: object) -> dict[str, object]:
    return {
        "job_kind": "terminate",
        "job_id": SESSION_ID,
        "target_session_id": SESSION_ID,
        "target_launch_id": LAUNCH_ID,
        **values,
    }


def test_registration_adopts_owner_only_launch_handle_and_reaper_stops_it(
    tmp_path: Path, monkeypatch
) -> None:
    process = _sleeper()
    monkeypatch.setattr(
        "yoke_harness.session_relay_termination.TERMINATE_WAIT_SECONDS",
        0.05,
    )
    try:
        assert record_supervised_native(
            LAUNCH_ID,
            process.pid,
            native_session_id=NATIVE_ID,
            state_dir=tmp_path,
        )
        assert adopt_launched_session(
            LAUNCH_ID,
            SESSION_ID,
            state_dir=tmp_path,
        )
        release_supervised_native(LAUNCH_ID, state_dir=tmp_path)
        handle = _handle_path(tmp_path)
        assert stat.S_IMODE(handle.stat().st_mode) == 0o600
        payload = json.loads(handle.read_text())
        assert payload["target_session_id"] == SESSION_ID
        assert payload["pid"] == process.pid

        result = reap_terminated_session(_job(), state_dir=tmp_path)

        assert result.result_code in {"terminated", "killed"}
        process.wait(timeout=5)
        assert not handle.exists()
        assert result.evidence == {
            "result_code": result.result_code,
            "handles_considered": 1,
        }
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_reused_pid_is_treated_as_an_already_exited_native(tmp_path: Path) -> None:
    handle = _handle_path(tmp_path)
    handle.parent.mkdir(mode=0o700)
    handle.write_text(
        json.dumps(
            {
                "launch_id": LAUNCH_ID,
                "target_session_id": SESSION_ID,
                "pid": os.getpid(),
                "process_start_time": "not-this-process-start",
            }
        )
    )

    result = reap_terminated_session(_job(), state_dir=tmp_path)

    assert result.result_code == "already_exited"
    assert not handle.exists()


def test_reaper_refuses_to_signal_its_own_process_group(tmp_path: Path) -> None:
    handle = _handle_path(tmp_path)
    handle.parent.mkdir(mode=0o700)
    handle.write_text(
        json.dumps(
            {
                "launch_id": LAUNCH_ID,
                "target_session_id": SESSION_ID,
                "pid": os.getpid(),
                "process_start_time": process_start_time(os.getpid()),
            }
        )
    )

    result = reap_terminated_session(_job(), state_dir=tmp_path)

    assert result.result_code == "shared_process_group"
    assert handle.exists()


def test_detached_resume_can_be_reaped_by_native_thread_identity(
    tmp_path: Path, monkeypatch
) -> None:
    process = _sleeper()
    monkeypatch.setattr(
        "yoke_harness.session_relay_termination.TERMINATE_WAIT_SECONDS",
        0.05,
    )
    try:
        assert record_supervised_native(
            LAUNCH_ID,
            process.pid,
            native_session_id=NATIVE_ID,
            supervision_kind="resume",
            state_dir=tmp_path,
        )

        result = reap_terminated_session(
            _job(target_launch_id=None, target_native_thread_id=NATIVE_ID),
            state_dir=tmp_path,
        )

        assert result.result_code in {"terminated", "killed"}
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_reaper_ignores_handles_without_the_target_identity(tmp_path: Path) -> None:
    process = _sleeper()
    try:
        assert record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            state_dir=tmp_path,
        )
        assert adopt_launched_session(
            LAUNCH_ID,
            "different-session",
            state_dir=tmp_path,
        )

        result = reap_terminated_session(_job(), state_dir=tmp_path)

        assert result.result_code == "not_found"
        assert process.poll() is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_claude_termination_names_a_missing_session_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    result = reap_terminated_session(
        _job(surface="claude-cli", target_native_thread_id=NATIVE_ID),
        state_dir=tmp_path,
    )

    assert result.result_code == "not_found"
    assert result.evidence["background_agent_result"] == "session_record_missing"
    assert "claude stop <job-id>" in result.evidence["background_agent_recovery"]
    assert result.evidence["handles_considered"] == 0
    assert redacted_evidence_document(result.evidence) == result.evidence


class _StopResult:
    """What a stop invocation reports back: only its exit status is read."""

    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_claude_termination_uses_the_per_pid_record_not_the_agent_listing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    claude_root = tmp_path / "claude"
    sessions = claude_root / "sessions"
    sessions.mkdir(parents=True)
    pid = 98127
    job_id = "7c5dcf5d"
    (sessions / f"{pid}.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "sessionId": NATIVE_ID,
                "kind": "bg",
                "jobId": job_id,
                "startedAt": 1_788_484_800_000,
            }
        )
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_root))
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_native.discover_claude_cli",
        lambda: "/usr/local/bin/claude",
    )
    oversized_listing = json.dumps(
        {"agents": [{"id": str(index)} for index in range(6_000)]}
    )
    assert len(oversized_listing.encode()) > 64 * 1024
    calls: list[tuple[str, ...]] = []

    def run(arguments: tuple[str, ...]) -> _StopResult:
        calls.append(arguments)
        if arguments[1] == "agents":
            return _StopResult(0, oversized_listing)
        return _StopResult(0)

    result = reap_terminated_session(
        _job(surface="claude-cli", target_native_thread_id=NATIVE_ID),
        state_dir=tmp_path,
        claude_process_runner=run,
    )

    assert result.result_code == "terminated"
    assert calls == [("/usr/local/bin/claude", "stop", job_id)]
    assert result.evidence == {
        "background_agent_result": "session_record_resolved",
        "background_agent_pid": pid,
        "background_agent_job_id": job_id,
        "background_agent_stop": "completed",
        "result_code": "terminated",
        "handles_considered": 0,
    }
    assert redacted_evidence_document(result.evidence) == result.evidence


def test_claude_termination_names_an_invalid_session_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "98127.json").write_text("not json")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))

    result = reap_terminated_session(
        _job(surface="claude-desktop", target_native_thread_id=NATIVE_ID),
        state_dir=tmp_path,
    )

    assert result.result_code == "outcome_unknown"
    assert result.evidence["background_agent_result"] == "session_record_invalid"
    assert result.evidence["background_agent_pid"] == 98127
    assert "rewrite its per-pid record" in result.evidence["background_agent_recovery"]
    assert redacted_evidence_document(result.evidence) == result.evidence


def test_a_known_job_id_is_stopped_without_listing_every_agent(monkeypatch) -> None:
    """The agent listing is the failure mode a caller holding the job id skips.

    Its output is read under a byte bound, and a machine with a few hundred
    background agents overruns it, so every identity resolved through it fails
    to parse and nothing is stopped.
    """
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_native.discover_claude_cli",
        lambda: "/usr/local/bin/claude",
    )

    def run(arguments: tuple[str, ...]) -> _StopResult:
        calls.append(arguments)
        return _StopResult(0)

    code, evidence = stop_claude_job("7c5dcf5d", process_runner=run)

    assert code == "terminated"
    assert calls == [("/usr/local/bin/claude", "stop", "7c5dcf5d")]
    assert evidence == {"background_agent_stop": "completed"}


def test_a_refused_job_stop_is_reported_as_failed(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_claude_native.discover_claude_cli",
        lambda: "/usr/local/bin/claude",
    )
    code, evidence = stop_claude_job(
        "7c5dcf5d", process_runner=lambda arguments: _StopResult(3)
    )
    assert code == "failed"
    assert evidence["background_agent_stop"] == "native_exit"


def test_runtime_dispatches_termination_without_project_checkout(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        "yoke_harness.session_relay_termination.reap_terminated_session",
        lambda job: sentinel,
    )

    assert run_registered_job(_job()) is sentinel
