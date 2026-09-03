"""A launched native's death is reported with the reason it left behind."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_harness.session_relay_native_capture_format import compose_capture
from yoke_harness.session_relay_native_diagnostics import native_diagnostic_path
from yoke_harness.session_relay_process_liveness import (
    native_account,
    verified_dead_sessions,
)
from yoke_harness.session_relay_termination import (
    NATIVE_HANDLE_DIRECTORY_NAME,
    local_state_root,
)


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
REFUSAL = "the model refused: credit balance is too low"


def _launch_handle(state_dir: Path, *, pid: int, start_time: str) -> Path:
    directory = local_state_root(state_dir) / NATIVE_HANDLE_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{LAUNCH_ID}.json"
    path.write_text(
        json.dumps(
            {
                "launch_id": LAUNCH_ID,
                "target_session_id": SESSION_ID,
                "pid": pid,
                "process_start_time": start_time,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _capture(state_dir: Path, *, exit_code: int) -> Path:
    path = native_diagnostic_path(f"nd-{LAUNCH_ID}", state_dir=state_dir)
    path.write_bytes(
        compose_capture(
            stdout=b"agent started\n",
            stderr=f"warming up\n{REFUSAL}\n".encode(),
            exit_code=exit_code,
            exit_at="2026-09-03T16:12:03Z",
        )
    )
    return path


def test_a_dead_launched_native_reports_its_launch_and_its_last_words(
    tmp_path: Path,
) -> None:
    _launch_handle(tmp_path, pid=4321, start_time="recorded-start")
    _capture(tmp_path, exit_code=1)

    dead = verified_dead_sessions(
        state_dir=tmp_path,
        anchors_dir=tmp_path / "anchors",
        # A reused pid names a different process, so this native is gone.
        start_time_of=lambda _pid: "some-other-start",
    )

    assert len(dead) == 1
    evidence = dead[0].evidence
    assert dead[0].session_id == SESSION_ID
    assert evidence["launch_id"] == LAUNCH_ID
    assert evidence["native_diagnostic_ref"] == f"nd-{LAUNCH_ID}"
    assert evidence["exit_code"] == 1
    assert evidence["native_exit_at"] == "2026-09-03T16:12:03Z"
    # The last line the native said, so the reason survives the machine that
    # produced it; the rest of the stream never leaves.
    assert evidence["native_stderr_tail"] == REFUSAL
    assert "warming up" not in json.dumps(evidence)


def test_a_live_launched_native_is_not_reported_at_all(tmp_path: Path) -> None:
    _launch_handle(tmp_path, pid=4321, start_time="recorded-start")

    dead = verified_dead_sessions(
        state_dir=tmp_path,
        anchors_dir=tmp_path / "anchors",
        start_time_of=lambda _pid: "recorded-start",
    )

    assert dead == ()


def test_a_launch_with_no_capture_still_reports_the_death(tmp_path: Path) -> None:
    _launch_handle(tmp_path, pid=4321, start_time="recorded-start")

    dead = verified_dead_sessions(
        state_dir=tmp_path,
        anchors_dir=tmp_path / "anchors",
        start_time_of=lambda _pid: None,
    )

    assert len(dead) == 1
    assert dead[0].evidence["launch_id"] == LAUNCH_ID
    assert "native_stderr_tail" not in dead[0].evidence


def test_a_native_account_is_empty_rather_than_raising_without_a_capture(
    tmp_path: Path,
) -> None:
    assert native_account(LAUNCH_ID, state_dir=tmp_path) == {}
    assert native_account("not-an-identifier", state_dir=tmp_path) == {}
