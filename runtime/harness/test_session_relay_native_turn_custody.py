"""A wake never starts a second native for a session already running one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.session_control.wake_delivery import (
    NATIVE_TURN_RUNNING_RESULT,
    delivery_attempt_failed,
)
from yoke_harness import session_relay_runtime
from yoke_harness import session_launch_handles
from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_relay_native_turn_custody import (
    RESUME_CUSTODY_SOURCE,
    deferral_for_running_native,
    running_native_for_session,
)
from yoke_harness.session_relay_process_liveness import LAUNCH_HANDLE_SOURCE


SESSION = "11111111-1111-4111-8111-111111111111"
OTHER_SESSION = "22222222-2222-4222-8222-222222222222"
RECORDED_START = "Mon Aug 24 08:00:00 2026"
REUSED_START = "Tue Aug 25 09:30:00 2026"
ATTEMPT = "33333333-3333-4333-8333-333333333333"


@pytest.fixture(autouse=True)
def _isolated_handles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the launch-handle family off the real machine cache.

    Resume custody is already redirected for the whole suite by the shared
    launch-custody isolation fixture, which is why these tests reach it
    through ``supervision_record_path`` rather than composing a directory.
    The handle family has no such fixture, so it is pinned here.
    """
    handles = tmp_path / "native-handles"
    handles.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        session_launch_handles, "native_handle_directory", lambda: handles
    )


def _start_time_of(live: dict[int, str]):
    def resolve(pid: int) -> str | None:
        return live.get(pid)

    return resolve


def _resume_record(
    state_dir: Path | None = None,
    *,
    session_id: str = SESSION,
    pid: int = 4001,
    attempt_id: str = ATTEMPT,
) -> None:
    """Write the custody record the relay writes when it starts a resume.

    Composed here rather than through ``record_supervised_native`` because
    that writer reads the live process table and refuses a pid that is not
    running, while these cases are about pids that deliberately are not.
    """
    path = supervision_record_path(attempt_id, state_dir)
    path.write_text(
        json.dumps(
            {
                "launch_id": attempt_id,
                "pid": pid,
                "process_start_time": RECORDED_START,
                "native_session_id": session_id,
                "supervision_kind": "resume",
                "lease_id": "lease-1",
            }
        ),
        encoding="utf-8",
    )


def _launch_handle(*, session_id: str = SESSION, pid: int = 5001) -> None:
    path = session_launch_handles.native_handle_directory() / "launch-1.json"
    path.write_text(
        json.dumps(
            {
                "launch_id": "launch-1",
                "target_session_id": session_id,
                "pid": pid,
                "process_start_time": RECORDED_START,
            }
        ),
        encoding="utf-8",
    )


def _wake_job(session_id: str = SESSION, *, workspace: Path | None = None) -> dict:
    return {
        "job_kind": "wake",
        "job_id": "44444444-4444-4444-8444-444444444444",
        "lease_id": "lease-2",
        "surface": "claude-cli",
        "project_id": 1,
        "target_workspace": str(workspace or Path.cwd()),
        "target_session_id": session_id,
        "message_id": "55555555-5555-4555-8555-555555555555",
        "native_instruction": "deliver 55555555-5555-4555-8555-555555555555",
    }


def test_a_live_resume_native_defers_the_wake(tmp_path: Path) -> None:
    _resume_record(tmp_path)
    running = running_native_for_session(
        SESSION,
        custody_state_dir=tmp_path,
        start_time_of=_start_time_of({4001: RECORDED_START}),
    )
    assert running is not None
    assert running.pid == 4001
    assert running.source == RESUME_CUSTODY_SOURCE
    assert running.evidence["result_code"] == NATIVE_TURN_RUNNING_RESULT


def test_a_live_launched_native_defers_the_wake(tmp_path: Path) -> None:
    _launch_handle()
    running = running_native_for_session(
        SESSION,
        custody_state_dir=tmp_path,
        start_time_of=_start_time_of({5001: RECORDED_START}),
    )
    assert running is not None
    assert running.source == LAUNCH_HANDLE_SOURCE


def test_a_dead_pid_does_not_defer(tmp_path: Path) -> None:
    _resume_record(tmp_path)
    _launch_handle()
    assert (
        running_native_for_session(
            SESSION,
            custody_state_dir=tmp_path,
            start_time_of=_start_time_of({}),
        )
        is None
    )


def test_a_reused_pid_reads_as_gone(tmp_path: Path) -> None:
    """The number came back as a different process, so the native is over."""
    _resume_record(tmp_path)
    assert (
        running_native_for_session(
            SESSION,
            custody_state_dir=tmp_path,
            start_time_of=_start_time_of({4001: REUSED_START}),
        )
        is None
    )


def test_a_session_with_no_record_proves_nothing(tmp_path: Path) -> None:
    _resume_record(tmp_path)
    _launch_handle()
    assert (
        running_native_for_session(
            OTHER_SESSION,
            custody_state_dir=tmp_path,
            start_time_of=_start_time_of({4001: RECORDED_START}),
        )
        is None
    )


def test_only_a_wake_job_is_ever_deferred(tmp_path: Path) -> None:
    _resume_record(tmp_path)
    context = session_relay_runtime.execution_context(
        {**_wake_job(workspace=tmp_path), "job_kind": "launch"}
    )
    assert (
        deferral_for_running_native(
            context,
            custody_state_dir=tmp_path,
            start_time_of=_start_time_of({4001: RECORDED_START}),
        )
        is None
    )


def test_the_runner_refuses_before_any_adapter_spawns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: list[str] = []

    def adapter(context):
        spawned.append(context.target_session_id or "")
        return session_relay_runtime.RelayAdapterResult("resumed_running")

    session_relay_runtime.reset_relay_adapters_for_tests()
    session_relay_runtime.register_relay_adapter("claude-cli", adapter)
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_custody.process_start_time",
        _start_time_of({4001: RECORDED_START}),
    )
    # The relay writes resume custody under the machine cache, which is where
    # the guard reads it from when no state directory is passed.
    _resume_record()

    result = session_relay_runtime.run_registered_job(_wake_job(workspace=tmp_path))

    assert result.result_code == NATIVE_TURN_RUNNING_RESULT
    assert result.evidence["running_native_pid"] == 4001
    assert spawned == []
    session_relay_runtime.reset_relay_adapters_for_tests()


def test_a_second_request_sees_the_first_native(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One machine runs one wake job at a time, and custody is written first.

    The spawner records custody before the adapter returns, so the next wake
    job this machine claims already sees it. Two requests therefore cannot
    both pass: the second reads the first one's record.
    """
    started: list[int] = []

    def adapter(context):
        del context
        _resume_record(pid=4001)
        started.append(4001)
        return session_relay_runtime.RelayAdapterResult("resumed_running")

    session_relay_runtime.reset_relay_adapters_for_tests()
    session_relay_runtime.register_relay_adapter("claude-cli", adapter)
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_custody.process_start_time",
        _start_time_of({4001: RECORDED_START}),
    )

    first = session_relay_runtime.run_registered_job(_wake_job(workspace=tmp_path))
    second = session_relay_runtime.run_registered_job(_wake_job(workspace=tmp_path))

    assert first.result_code == "resumed_running"
    assert second.result_code == NATIVE_TURN_RUNNING_RESULT
    assert started == [4001]
    session_relay_runtime.reset_relay_adapters_for_tests()


def test_a_wake_after_the_native_exits_is_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resumed: list[str] = []

    def adapter(context):
        resumed.append(context.target_session_id or "")
        return session_relay_runtime.RelayAdapterResult("resumed_running")

    session_relay_runtime.reset_relay_adapters_for_tests()
    session_relay_runtime.register_relay_adapter("claude-cli", adapter)
    _resume_record()
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_custody.process_start_time",
        _start_time_of({}),
    )

    result = session_relay_runtime.run_registered_job(_wake_job(workspace=tmp_path))

    assert result.result_code == "resumed_running"
    assert resumed == [SESSION]
    session_relay_runtime.reset_relay_adapters_for_tests()


def test_a_deferral_is_not_reported_as_a_failure() -> None:
    assert delivery_attempt_failed(NATIVE_TURN_RUNNING_RESULT) is False
