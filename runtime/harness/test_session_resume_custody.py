"""Custody of a detached resume: is this native still working?

A resume is contained for going quiet or for no longer being the process the
record names — never for how long it has been running. Launch-registration
containment, a different question with a different deadline, lives in
:mod:`test_session_launch_containment`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from yoke_contracts.session_control.resume import RESUME_INACTIVITY_SECONDS
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    touch_supervised_resume,
)
from yoke_harness.session_launch_containment_sweep import (
    contain_stranded_launch_natives,
)


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _record_file(state_dir: Path) -> Path:
    return state_dir / "session-launch-supervision" / f"{LAUNCH_ID}.json"


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


def test_an_active_resume_outlives_any_elapsed_time(tmp_path: Path) -> None:
    # The reported defect: a resume doing productive work was terminated for
    # nothing but having started long ago. Custody reads activity, not age.
    process = _sleeper()
    now = time.time()
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            state_dir=tmp_path,
            now=now - (6 * 60 * 60),
        )
        assert touch_supervised_resume(LAUNCH_ID, state_dir=tmp_path, now=now - 60)

        assert contain_stranded_launch_natives(state_dir=tmp_path, now=now) == []
        assert _record_file(tmp_path).exists()
        assert process.poll() is None
    finally:
        process.kill()
        process.wait()


def test_a_stale_capture_does_not_prove_a_quiet_resume_is_working(
    tmp_path: Path,
) -> None:
    process = _sleeper()
    now = time.time()
    stale = now - RESUME_INACTIVITY_SECONDS - 1
    capture = tmp_path / "resume.capture"
    capture.write_text("output from before the quiet window")
    os.utime(capture, (stale, stale))
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            capture_path=capture,
            state_dir=tmp_path,
            now=stale,
        )

        outcomes = contain_stranded_launch_natives(state_dir=tmp_path, now=now)

        assert [outcome.reason for outcome in outcomes] == ["inactivity"]
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_a_missing_capture_does_not_prove_a_quiet_resume_is_working(
    tmp_path: Path,
) -> None:
    process = _sleeper()
    now = time.time()
    try:
        record_supervised_native(
            LAUNCH_ID,
            process.pid,
            supervision_kind="resume",
            capture_path=tmp_path / "never-written.capture",
            state_dir=tmp_path,
            now=now - RESUME_INACTIVITY_SECONDS - 1,
        )

        outcomes = contain_stranded_launch_natives(state_dir=tmp_path, now=now)

        assert [outcome.reason for outcome in outcomes] == ["inactivity"]
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
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
        retained = json.loads(_record_file(tmp_path).read_text())
        assert retained["containment_reason"] == "inactivity"
        assert retained["contained_at"]
        assert contain_stranded_launch_natives(state_dir=tmp_path, now=now) == []
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
