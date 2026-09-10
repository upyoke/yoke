"""Dead resume custody outranks a spent launch handle in death evidence."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_harness.session_launch_containment import supervision_record_path
from yoke_harness.session_launch_handles import native_handle_path
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
