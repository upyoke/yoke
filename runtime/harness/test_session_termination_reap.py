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
        "yoke_harness.session_relay_termination._TERMINATE_WAIT_SECONDS",
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
        "yoke_harness.session_relay_termination._TERMINATE_WAIT_SECONDS",
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


def test_claude_termination_reaps_the_relay_owned_process_alone(
    tmp_path: Path,
) -> None:
    """Nothing but this machine's own records names a Claude session's process.

    While a daemon owned the session, terminating one meant asking that daemon
    to stop a job first, and a listing that came back empty left the process
    running with nobody accountable for it.
    """
    result = reap_terminated_session(
        _job(surface="claude-cli", target_native_thread_id=NATIVE_ID),
        state_dir=tmp_path,
    )

    assert result.result_code == "not_found"
    assert result.evidence == {"result_code": "not_found", "handles_considered": 0}
    assert redacted_evidence_document(result.evidence) == result.evidence


def test_runtime_dispatches_termination_without_project_checkout(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        "yoke_harness.session_relay_termination.reap_terminated_session",
        lambda job: sentinel,
    )

    assert run_registered_job(_job()) is sentinel
