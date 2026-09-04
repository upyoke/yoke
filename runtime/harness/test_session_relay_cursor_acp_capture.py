"""A Cursor bootstrap turn writes its own account, however that turn ends."""

from __future__ import annotations

from pathlib import Path

from yoke_harness.session_relay_cursor_acp_capture import turn_record
from yoke_harness.session_relay_native_capture_format import parse_capture
from yoke_harness.session_relay_native_diagnostics import native_diagnostic_path


LAUNCH_ID = "44444444-4444-4444-8444-444444444444"
REFUSAL = "cursor-agent: authentication required"


def _read(state_dir: Path):
    return parse_capture(
        native_diagnostic_path(
            f"nd-{LAUNCH_ID}", state_dir=state_dir, create=False
        ).read_bytes()
    )


def test_a_bootstrap_turn_error_lands_in_the_launch_capture(tmp_path: Path) -> None:
    turn = turn_record(LAUNCH_ID, state_dir=tmp_path)

    turn.failed(TimeoutError("ACP response timed out"))
    turn.record_exit(f"{REFUSAL}\n".encode(), 1)

    capture = _read(tmp_path)
    assert capture is not None
    assert capture.exited
    assert capture.exit_code == 1
    # The turn's own fate, which used to be discarded inside a bare except.
    assert b"turn failed: TimeoutError: ACP response timed out" in capture.stdout
    # The ACP child's stderr, which used to be reported nowhere at all.
    assert capture.tail == REFUSAL


def test_an_answered_turn_names_its_stop_reason_while_the_child_still_runs(
    tmp_path: Path,
) -> None:
    turn = turn_record(LAUNCH_ID, state_dir=tmp_path)

    turn.answered({"id": 1, "result": {"stopReason": "end_turn"}})
    turn.record_open(b"")

    capture = _read(tmp_path)
    assert capture is not None
    assert not capture.exited
    assert b"turn answered: stopReason=end_turn" in capture.stdout


def test_a_turn_with_no_launch_to_name_writes_nothing(tmp_path: Path) -> None:
    turn = turn_record(None, state_dir=tmp_path)

    turn.failed(RuntimeError("ACP exited"))
    turn.record_exit(b"", None)

    assert turn.capture is None
    assert not (tmp_path / "native-diagnostics").exists()
