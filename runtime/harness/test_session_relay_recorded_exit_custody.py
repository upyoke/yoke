"""A native whose supervisor recorded its exit no longer holds a wake.

Every resume runs in its own process group, and a background command the
turn started can outlive the native in that group. The group then still has
members, so group custody alone reads the turn as running and every wake to
the session is held until someone terminates it. The supervisor waited on the
native and wrote its exit into the capture, so that record decides first.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_harness import session_relay_native_turn_custody as custody
from yoke_harness import session_relay_runtime
from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_relay_native_capture_format import (
    STATE_EXITED,
    STATE_RUNNING,
    compose_capture,
)


SESSION = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "33333333-3333-4333-8333-333333333333"
RECORDED_START = "Mon Aug 24 08:00:00 2026"


def _group_resume(tmp_path: Path, *, capture_state: str | None) -> None:
    """Write grouped resume custody whose leader is gone but group is not."""
    capture = None
    if capture_state is not None:
        capture = tmp_path / "native.capture"
        capture.write_bytes(
            compose_capture(
                stdout=b"",
                stderr=b"",
                state=capture_state,
                exit_code=0 if capture_state == STATE_EXITED else None,
            )
        )
    supervision_record_path(ATTEMPT).write_text(
        json.dumps(
            {
                "launch_id": ATTEMPT,
                "pid": 4001,
                "process_start_time": RECORDED_START,
                "process_group_id": 4001,
                "group_members": {"4001": RECORDED_START},
                "native_session_id": SESSION,
                "supervision_kind": "resume",
                "lease_id": "lease-1",
                "capture_path": str(capture) if capture else None,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def group_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    """A background command the turn started still lives in its group."""
    monkeypatch.setattr(custody, "custody_state", lambda record: "live")


def _wake(surface: str, workspace: Path) -> dict:
    return {
        "job_kind": "wake",
        "job_id": "44444444-4444-4444-8444-444444444444",
        "lease_id": "lease-2",
        "surface": surface,
        "project_id": 1,
        "target_workspace": str(workspace),
        "target_session_id": SESSION,
        "message_id": "55555555-5555-4555-8555-555555555555",
        "native_instruction": "deliver 55555555-5555-4555-8555-555555555555",
    }


@pytest.mark.parametrize("surface", ["claude-cli", "codex-cli", "cursor-cli"])
def test_a_recorded_exit_lets_the_wake_resume_the_same_session(
    surface: str, tmp_path: Path, group_survives: None
) -> None:
    resumed: list[str] = []

    def adapter(context):
        resumed.append(context.target_session_id or "")
        return session_relay_runtime.RelayAdapterResult("resumed_running")

    session_relay_runtime.reset_relay_adapters_for_tests()
    session_relay_runtime.register_relay_adapter(surface, adapter)
    _group_resume(tmp_path, capture_state=STATE_EXITED)
    try:
        result = session_relay_runtime.run_registered_job(_wake(surface, tmp_path))
    finally:
        session_relay_runtime.reset_relay_adapters_for_tests()

    assert result.result_code == "resumed_running"
    assert resumed == [SESSION]


def test_the_finished_resume_is_named_for_the_dead_report(
    tmp_path: Path, group_survives: None
) -> None:
    _group_resume(tmp_path, capture_state=STATE_EXITED)
    assert custody.running_native_for_session(SESSION) is None
    finished = custody.finished_resume_for_session(SESSION)
    assert finished is not None and finished.attempt_id == ATTEMPT


@pytest.mark.parametrize("capture_state", [STATE_RUNNING, None])
def test_an_unsettled_native_still_holds_the_wake(
    capture_state: str | None, tmp_path: Path, group_survives: None
) -> None:
    """No recorded exit: a supervisor killed mid-turn leaves its native running.

    That is the exactly-once guard -- the wake never starts a second turn
    beside a native the machine cannot prove has ended.
    """
    _group_resume(tmp_path, capture_state=capture_state)
    context = session_relay_runtime.execution_context(_wake("cursor-cli", tmp_path))
    deferred = custody.deferral_for_running_native(context)
    assert deferred is not None
    assert deferred.result_code == NATIVE_TURN_RUNNING_RESULT
    assert custody.finished_resume_for_session(SESSION) is None
