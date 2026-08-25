"""Containment of natives whose launch never reached a registered session."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from yoke_harness.session_launch_containment import (
    CONTAINMENT_TTL_SECONDS,
    contain_stranded_launch_natives,
    record_supervised_native,
    release_supervised_native,
    touch_supervised_resume,
)
from yoke_contracts.session_control.resume import RESUME_INACTIVITY_SECONDS


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _record_file(state_dir: Path) -> Path:
    return state_dir / "session-launch-supervision" / f"{LAUNCH_ID}.json"


def test_a_recorded_native_carries_its_pid_and_session(tmp_path: Path) -> None:
    process = _sleeper()
    try:
        assert record_supervised_native(
            LAUNCH_ID,
            process.pid,
            native_session_id=SESSION_ID,
            state_dir=tmp_path,
        )
        payload = json.loads(_record_file(tmp_path).read_text())
        assert payload["launch_id"] == LAUNCH_ID
        assert payload["pid"] == process.pid
        assert payload["native_session_id"] == SESSION_ID
        assert payload["process_start_time"]
    finally:
        process.kill()
        process.wait()


def test_registration_releases_the_native_from_supervision(tmp_path: Path) -> None:
    process = _sleeper()
    try:
        record_supervised_native(LAUNCH_ID, process.pid, state_dir=tmp_path)
        release_supervised_native(LAUNCH_ID, state_dir=tmp_path)

        assert not _record_file(tmp_path).exists()
        assert contain_stranded_launch_natives(state_dir=tmp_path, ttl_seconds=0) == []
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()


def test_a_native_inside_its_window_is_left_alone(tmp_path: Path) -> None:
    process = _sleeper()
    try:
        record_supervised_native(LAUNCH_ID, process.pid, state_dir=tmp_path)

        assert contain_stranded_launch_natives(state_dir=tmp_path) == []
        assert _record_file(tmp_path).exists()
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()


def test_a_native_past_its_window_is_terminated(tmp_path: Path) -> None:
    process = _sleeper()
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            native_session_id=SESSION_ID,
            state_dir=tmp_path,
            now=time.time() - CONTAINMENT_TTL_SECONDS - 1,
        )

        outcomes = contain_stranded_launch_natives(state_dir=tmp_path)

        assert [outcome.launch_id for outcome in outcomes] == [LAUNCH_ID]
        assert outcomes[0].native_session_id == SESSION_ID
        assert outcomes[0].result in {"terminated", "killed"}
        assert process.wait(timeout=10) is not None
        # The record is consumed, so a later sweep cannot signal a reused pid.
        assert not _record_file(tmp_path).exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_the_whole_process_group_goes_down_with_the_native(tmp_path: Path) -> None:
    # A native that spawned its own children leaves them running unless the
    # group is signalled, which is exactly the freelancing shape being closed.
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time;"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
            "print(child.pid,flush=True);"
            "time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    child_pid = int(leader.stdout.readline().strip())
    try:
        record_supervised_native(
            LAUNCH_ID,
            leader.pid,
            state_dir=tmp_path,
            now=time.time() - CONTAINMENT_TTL_SECONDS - 1,
        )

        contain_stranded_launch_natives(state_dir=tmp_path)

        leader.wait(timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        else:  # pragma: no cover - the child outlived its group
            raise AssertionError("the native's child survived containment")
    finally:
        for pid in (leader.pid, child_pid):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        leader.wait()


def test_a_reused_pid_is_reported_exited_rather_than_signalled(
    tmp_path: Path,
) -> None:
    process = _sleeper()
    process.kill()
    process.wait()
    record_supervised_native(
        LAUNCH_ID,
        os.getpid(),
        state_dir=tmp_path,
        now=time.time() - CONTAINMENT_TTL_SECONDS - 1,
    )
    payload = json.loads(_record_file(tmp_path).read_text())
    payload["process_start_time"] = "a start time this process never had"
    _record_file(tmp_path).write_text(json.dumps(payload))

    outcomes = contain_stranded_launch_natives(state_dir=tmp_path)

    assert [outcome.result for outcome in outcomes] == ["already_exited"]


def test_recording_refuses_a_pid_that_does_not_exist(tmp_path: Path) -> None:
    process = _sleeper()
    process.kill()
    process.wait()

    assert not record_supervised_native(LAUNCH_ID, process.pid, state_dir=tmp_path)
    assert not record_supervised_native(LAUNCH_ID, 0, state_dir=tmp_path)
    assert not record_supervised_native("", os.getpid(), state_dir=tmp_path)


def test_recent_resume_hook_activity_keeps_detached_native_alive(
    tmp_path: Path,
) -> None:
    process = _sleeper()
    now = time.time()
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            state_dir=tmp_path,
            now=now - RESUME_INACTIVITY_SECONDS - 1,
        )
        assert touch_supervised_resume(LAUNCH_ID, state_dir=tmp_path, now=now)

        assert contain_stranded_launch_natives(state_dir=tmp_path, now=now) == []
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()


def test_quiet_resume_is_reaped_with_inactivity_evidence(tmp_path: Path) -> None:
    process = _sleeper()
    now = time.time()
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            state_dir=tmp_path,
            now=now - RESUME_INACTIVITY_SECONDS - 1,
        )

        outcomes = contain_stranded_launch_natives(state_dir=tmp_path, now=now)

        assert len(outcomes) == 1
        assert outcomes[0].supervision_kind == "resume"
        assert outcomes[0].reason == "inactivity"
        assert outcomes[0].result in {"terminated", "killed"}
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_recent_capture_output_keeps_silent_resume_alive(tmp_path: Path) -> None:
    process = _sleeper()
    now = time.time()
    capture = tmp_path / "resume.capture"
    capture.write_text("recent native output")
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            capture_path=capture,
            state_dir=tmp_path,
            now=now - RESUME_INACTIVITY_SECONDS - 1,
        )

        assert contain_stranded_launch_natives(state_dir=tmp_path, now=now) == []
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()
