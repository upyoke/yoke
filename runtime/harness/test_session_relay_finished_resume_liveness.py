"""Dead resume custody outranks a spent launch handle in death evidence."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_launch_handles import native_handle_path
from yoke_harness.session_relay_native_capture_format import compose_capture
from yoke_harness.session_relay_native_diagnostics import (
    diagnostic_reference,
    native_diagnostic_path,
)
from yoke_harness.session_relay_process_liveness import verified_dead_sessions


DEAD_SESSION = "22222222-2222-4222-8222-222222222222"
RECORDED_START = "Mon Aug 24 08:00:00 2026"


def test_a_dead_resume_names_its_own_process_not_the_spent_launch(
    tmp_path: Path,
) -> None:
    anchors = tmp_path / ANCHORS_DIR_NAME
    anchors.mkdir(parents=True, exist_ok=True)
    handle = native_handle_path("launch-resume-outrank")
    resume = supervision_record_path("resume-4004", tmp_path)
    handle.parent.mkdir(parents=True, exist_ok=True)
    resume.parent.mkdir(parents=True, exist_ok=True)
    handle.write_text(
        json.dumps(
            {
                "launch_id": "launch-resume-outrank",
                "target_session_id": DEAD_SESSION,
                "pid": 4002,
                "process_start_time": RECORDED_START,
            }
        ),
        encoding="utf-8",
    )
    resume.write_text(
        json.dumps(
            {
                "launch_id": "resume-4004",
                "pid": 4004,
                "process_start_time": RECORDED_START,
                "native_session_id": DEAD_SESSION,
                "supervision_kind": "resume",
            }
        ),
        encoding="utf-8",
    )

    try:
        dead = verified_dead_sessions(
            state_dir=tmp_path,
            anchors_dir=anchors,
            start_time_of=lambda _pid: None,
        )
        assert dead[0].evidence["pids"] == [4004]
        assert dead[0].evidence["process_start_times"] == {"4004": RECORDED_START}
        assert dead[0].evidence["attempt_id"] == "resume-4004"
        assert dead[0].evidence["launch_id"] == "launch-resume-outrank"
    finally:
        handle.unlink(missing_ok=True)


def test_contained_resume_without_handle_or_anchor_is_reported(tmp_path):
    resume = supervision_record_path("resume-without-hook", tmp_path)
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text(
        json.dumps(
            {
                "launch_id": "resume-without-hook",
                "pid": 4004,
                "process_start_time": RECORDED_START,
                "target_session_id": DEAD_SESSION,
                "supervision_kind": "resume",
                "containment_reason": "inactivity",
            }
        )
    )
    dead = verified_dead_sessions(
        state_dir=tmp_path,
        anchors_dir=tmp_path / "empty-anchors",
        start_time_of=lambda pid: None,
    )
    entry = next(entry for entry in dead if entry.session_id == DEAD_SESSION)
    assert entry.evidence["pids"] == [4004]
    assert entry.evidence["containment_reason"] == "inactivity"
    assert entry.record_paths == (resume,)


def test_custody_comes_from_the_machine_cache_and_the_account_from_the_relay(
    tmp_path: Path,
) -> None:
    """The relay passes only its own directory, which holds captures.

    Custody is in the machine cache, where the wake's custody check reads it;
    reading it from the relay directory hid every resume from this reporter.
    """
    attempt = "66666666-6666-4666-8666-666666666666"
    relay = tmp_path / "relay-instance"
    supervision_record_path(attempt).write_text(
        json.dumps(
            {
                "launch_id": attempt,
                "pid": 4004,
                "process_start_time": RECORDED_START,
                "target_session_id": DEAD_SESSION,
                "supervision_kind": "resume",
            }
        ),
        encoding="utf-8",
    )
    native_diagnostic_path(
        diagnostic_reference(attempt), state_dir=relay, create=True
    ).write_bytes(compose_capture(stdout=b"", stderr=b"", exit_code=0))
    dead = verified_dead_sessions(
        diagnostic_state_dir=relay,
        anchors_dir=tmp_path / "empty-anchors",
        start_time_of=lambda pid: None,
    )
    entry = next(entry for entry in dead if entry.session_id == DEAD_SESSION)
    assert entry.evidence["attempt_id"] == attempt
    assert entry.evidence["exit_code"] == 0
