"""A native's account reaches its capture while the turn is still running.

Three facts have to hold together for a stalled native to be tellable from a
working one: the turn streams rather than speaking once at the end, the
supervisor's refresh reports itself rather than only the native, and the
native's own clock is recorded separately from the file's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from yoke_harness import session_relay_native_supervisor as supervisor

from yoke_harness.session_relay_cursor_cli import cursor_turn_command
from yoke_harness.session_relay_native_capture_format import (
    STATE_RUNNING,
    compose_capture,
    parse_capture,
)
from yoke_harness.session_relay_native_turn_custody import RunningNative


def _command(**overrides) -> list[str]:
    return cursor_turn_command(
        overrides.pop("binary", "cursor-agent"),
        resume_session_id=overrides.pop("resume_session_id", None),
        checkout=overrides.pop("checkout", "/checkouts/alpha"),
        instruction=overrides.pop("instruction", "do the thing"),
        model=overrides.pop("model", None),
    )


def test_a_cursor_turn_streams_its_account() -> None:
    """``json`` emits nothing until the end, which is what hid two stalls."""
    command = _command()
    assert "--output-format" in command
    assert command[command.index("--output-format") + 1] == "stream-json"


def test_a_resume_streams_on_the_same_terms() -> None:
    """Both routes, or the stall signal has a blind side."""
    command = _command(resume_session_id="0f6d1bd6-3a3b-4d6a-9a0e-2a2b1c4d5e6f")
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert "--resume" in command


def test_the_terminal_result_is_still_the_last_line_a_reader_finds() -> None:
    """The stream ends at the same envelope a single document was.

    The result reader scans a capture's lines newest first, so streaming
    changes what precedes the result and not the result itself.
    """
    stream = b"\n".join(
        (
            json.dumps({"type": "system"}).encode(),
            json.dumps({"type": "assistant"}).encode(),
            json.dumps({"type": "result", "subtype": "success"}).encode(),
        )
    )
    capture = parse_capture(compose_capture(stdout=stream, stderr=b""))
    assert capture is not None
    newest_first = [
        line for line in reversed(bytes(capture.stdout).decode().splitlines()) if line
    ]
    assert json.loads(newest_first[0])["type"] == "result"


def test_the_native_clock_is_recorded_apart_from_the_file() -> None:
    """``last-output-at`` is the native's; the file's mtime is the supervisor's."""
    payload = compose_capture(
        stdout=b"",
        stderr=b"",
        state=STATE_RUNNING,
        last_output_at="2026-09-18T14:24:36Z",
    )
    capture = parse_capture(payload)
    assert capture is not None
    assert capture.last_output_at == "2026-09-18T14:24:36Z"
    assert capture.state == STATE_RUNNING


def test_a_capture_without_the_clock_still_reads() -> None:
    """Captures written before the field exists must not become unreadable."""
    capture = parse_capture(compose_capture(stdout=b"out", stderr=b""))
    assert capture is not None
    assert capture.last_output_at is None


def test_a_deferral_reports_the_silence_it_measured() -> None:
    running = RunningNative(
        session_id="target",
        pid=4001,
        process_start_time="Fri Sep 18 10:24:24 2026",
        source="launch_handle",
        silent_for_seconds=1800,
    )
    assert running.evidence["running_native_silent_for_seconds"] == 1800


def test_an_unmeasurable_silence_is_absent_rather_than_zero() -> None:
    """No capture to read is not the same as a native that just spoke."""
    running = RunningNative(
        session_id="target",
        pid=4001,
        process_start_time="Fri Sep 18 10:24:24 2026",
        source="launch_handle",
    )
    assert "running_native_silent_for_seconds" not in running.evidence


def _silent_native(seconds: float) -> list[str]:
    """A native that says nothing and takes its time about it."""
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def test_a_silent_native_still_refreshes_its_capture(
    tmp_path: Path, monkeypatch
) -> None:
    """The refresh reports the supervisor, so silence cannot freeze it.

    It once ran only when the native had new output, which reads correctly
    until a native has none: one cursor capture sat at the modification time
    of its spawn for an hour, indistinguishable from a file whose supervisor
    had died.
    """
    monkeypatch.setattr(supervisor, "FLUSH_INTERVAL_SECONDS", 0.05)
    writes: list[str] = []
    original = supervisor._write

    def counted(capture, streams, **kwargs):
        writes.append(str(kwargs.get("state")))
        return original(capture, streams, **kwargs)

    monkeypatch.setattr(supervisor, "_write", counted)

    assert supervisor.supervise(tmp_path / "nd-silent.capture", _silent_native(0.4)) == 0

    running = [state for state in writes if state == "running"]
    # The spawn write plus at least one interval write: the file's clock moved
    # while the native said nothing at all.
    assert len(running) > 1


def test_a_silent_native_records_when_it_last_spoke(tmp_path: Path) -> None:
    """A turn that never speaks is silent from its spawn, and says so."""
    capture_path = tmp_path / "nd-quiet.capture"

    assert supervisor.supervise(capture_path, _silent_native(0.05)) == 0

    capture = parse_capture(capture_path.read_bytes())
    assert capture is not None
    assert capture.stdout == b""
    assert capture.last_output_at is not None
