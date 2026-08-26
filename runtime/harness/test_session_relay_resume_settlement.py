"""Detached resume outcome collection and terminal wake settlement tests."""

from __future__ import annotations

from pathlib import Path
import os
import sys
import time

from yoke_contracts.session_control.resume import (
    RESUME_EXITED_NONZERO_RESULT,
    RESUMED_COMPLETED_RESULT,
    RESUMED_DIED_RESULT,
)
from yoke_harness import session_relay_resume_settlement as settlement
from yoke_harness.session_launch_containment import record_supervised_native
from yoke_harness.session_relay_claude_resume import spawn_detached_claude_resume
from yoke_harness.session_relay_resume_settlement import (
    finished_native_resumes,
    settle_finished_native_resumes,
    supervised_resumes,
)
from yoke_harness.session_relay_resume_watch import (
    resume_outcome_path,
    write_resume_outcome,
)


ATTEMPT_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
LEASE_ID = "lease-1"
REFUSAL = "Session is running as a background agent (bg). Use claude agents."
FUNCTION_ID = "session_control.relay.report"


class _Response:
    def __init__(self, success: bool = True) -> None:
        self.success = success


class _Dispatcher:
    def __init__(self, success: bool = True) -> None:
        self.calls: list[dict] = []
        self._success = success

    def __call__(self, *, function_id, target, payload, timeout_s):
        del target, timeout_s
        self.calls.append({"function_id": function_id, **payload})
        return _Response(self._success)


def _spawn(tmp_path: Path, script: str):
    return spawn_detached_claude_resume(
        [sys.executable, "-c", script],
        checkout=tmp_path,
        environment=dict(os.environ),
        attempt_id=ATTEMPT_ID,
        native_session_id=SESSION_ID,
        binary_source="path",
        lease_id=LEASE_ID,
        state_dir=tmp_path,
    )


def _await_outcome(capture_path: Path) -> Path:
    outcome = resume_outcome_path(capture_path)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if outcome.exists():
            return outcome
        time.sleep(0.05)
    raise AssertionError(f"resume supervisor never recorded an outcome at {outcome}")


def test_native_exiting_nonzero_settles_the_attempt_with_a_failure_result(
    tmp_path: Path,
) -> None:
    resumed = _spawn(
        tmp_path,
        f"import sys; sys.stderr.write({REFUSAL!r}); sys.exit(3)",
    )

    assert resumed is not None
    _await_outcome(resumed.capture_path)
    dispatcher = _Dispatcher()

    settled = settle_finished_native_resumes(
        dispatcher,
        FUNCTION_ID,
        relay_id="machine:relay",
        machine_id="33333333-3333-4333-8333-333333333333",
        state_dir=tmp_path,
        timeout_s=5,
    )

    assert settled == (ATTEMPT_ID,)
    report = dispatcher.calls[0]
    assert report["job_kind"] == "wake"
    assert report["job_id"] == ATTEMPT_ID
    assert report["lease_id"] == LEASE_ID
    assert report["result"] == RESUME_EXITED_NONZERO_RESULT
    assert report["evidence"]["exit_code"] == 3
    assert report["evidence"]["native_error_step"] == "resume"
    assert report["evidence"]["native_error_class"] == "process_exit"
    assert report["evidence"]["diagnostic_availability"] == "relay_local"
    assert report["evidence"]["native_diagnostic_ref"].startswith("nd-")
    assert REFUSAL not in str(report["evidence"])
    assert supervised_resumes(tmp_path) == ()
    assert not resume_outcome_path(resumed.capture_path).exists()


def test_native_exiting_cleanly_settles_the_attempt_as_completed(
    tmp_path: Path,
) -> None:
    resumed = _spawn(tmp_path, "print('resumed turn')")

    assert resumed is not None
    _await_outcome(resumed.capture_path)
    dispatcher = _Dispatcher()

    settle_finished_native_resumes(
        dispatcher,
        FUNCTION_ID,
        relay_id="machine:relay",
        machine_id="33333333-3333-4333-8333-333333333333",
        state_dir=tmp_path,
        timeout_s=5,
    )

    report = dispatcher.calls[0]
    assert report["result"] == RESUMED_COMPLETED_RESULT
    assert report["evidence"]["exit_code"] == 0
    assert "native_diagnostic_ref" not in report["evidence"]


def test_a_running_resume_is_left_alone_until_its_outcome_lands(
    tmp_path: Path,
) -> None:
    capture = tmp_path / f"{ATTEMPT_ID}.capture"
    capture.write_bytes(b"still reasoning\n")
    record_supervised_native(
        ATTEMPT_ID,
        # This process is alive and its start time matches, which is exactly
        # the shape of a resume still working through its turn.
        os.getpid(),
        native_session_id=SESSION_ID,
        supervision_kind="resume",
        capture_path=capture,
        lease_id=LEASE_ID,
        state_dir=tmp_path,
    )

    assert finished_native_resumes(state_dir=tmp_path) == ()

    write_resume_outcome(resume_outcome_path(capture), exit_code=9)

    finished = finished_native_resumes(state_dir=tmp_path)
    assert len(finished) == 1
    assert finished[0].result.result_code == RESUME_EXITED_NONZERO_RESULT


def test_a_vanished_resume_without_an_outcome_settles_as_died(
    tmp_path: Path,
    monkeypatch,
) -> None:
    capture = tmp_path / f"{ATTEMPT_ID}.capture"
    capture.write_bytes(b"contained mid-turn\n")
    record_supervised_native(
        ATTEMPT_ID,
        os.getpid(),
        native_session_id=SESSION_ID,
        supervision_kind="resume",
        capture_path=capture,
        lease_id=LEASE_ID,
        state_dir=tmp_path,
    )
    # The supervisor was killed alongside the native it was waiting on, so no
    # outcome was ever written and the recorded process is gone.
    monkeypatch.setattr(settlement, "process_start_time", lambda pid: None)

    finished = finished_native_resumes(state_dir=tmp_path)

    assert len(finished) == 1
    assert finished[0].result.result_code == RESUMED_DIED_RESULT
    assert "exit_code" not in finished[0].result.evidence


def test_a_failed_report_keeps_the_record_for_the_next_poll(tmp_path: Path) -> None:
    capture = tmp_path / f"{ATTEMPT_ID}.capture"
    capture.write_bytes(b"refused\n")
    record_supervised_native(
        ATTEMPT_ID,
        os.getpid(),
        native_session_id=SESSION_ID,
        supervision_kind="resume",
        capture_path=capture,
        lease_id=LEASE_ID,
        state_dir=tmp_path,
    )
    write_resume_outcome(resume_outcome_path(capture), exit_code=1)

    settled = settle_finished_native_resumes(
        _Dispatcher(success=False),
        FUNCTION_ID,
        relay_id="machine:relay",
        machine_id="33333333-3333-4333-8333-333333333333",
        state_dir=tmp_path,
        timeout_s=5,
    )

    assert settled == ()
    assert len(supervised_resumes(tmp_path)) == 1
