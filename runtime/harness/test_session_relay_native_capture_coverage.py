"""Every harness keeps what its native said, on spawn and on resume."""

from __future__ import annotations

from pathlib import Path

from yoke_harness import session_relay_codex_cli as codex_cli
from yoke_harness import session_relay_cursor_cli as cursor_cli
from yoke_harness.session_relay_cursor import CursorWakeRequest
from yoke_harness.session_relay_native_capture_format import parse_capture
from yoke_harness.session_relay_native_diagnostics import (
    native_diagnostic_path,
    store_native_diagnostic,
)
from yoke_harness.session_relay_native_streams import (
    STDERR,
    STDOUT,
    BoundedStreams,
)


ATTEMPT_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"


def test_a_cursor_resume_runs_supervised_instead_of_discarding_its_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    spawned: dict[str, object] = {}

    class _Process:
        pid = 4321

    monkeypatch.setattr(cursor_cli, "resolve_native_cli", lambda _name: "/opt/cursor")
    monkeypatch.setattr(
        cursor_cli,
        "spawn_supervised_native",
        lambda argv, **kwargs: (
            spawned.update(argv=list(argv), **kwargs)
            or cursor_cli.SupervisedNative(
                _Process.pid,
                str(argv[0]),
                "path",
                tmp_path / f"nd-{ATTEMPT_ID}.capture",
                f"nd-{ATTEMPT_ID}",
                "2026-09-03T16:00:00Z",
            )
        ),
    )

    result = cursor_cli.CursorCliTransport().resume_chat(
        CursorWakeRequest(
            checkout=tmp_path,
            target_session_id=SESSION_ID,
            surface_version="2026.08.31",
            target_liveness="stopped",
            wake_mode="waiting",
            native_instruction="check your inbox",
            attempt_id=ATTEMPT_ID,
            lease_id="lease-1",
        )
    )

    assert result.result_code == "accepted"
    # The reference is what maps this attempt back to what the native said;
    # this transport used to send both streams to /dev/null.
    assert result.diagnostic_ref == f"nd-{ATTEMPT_ID}"
    assert result.capture_path == str(tmp_path / f"nd-{ATTEMPT_ID}.capture")
    assert spawned["attempt_id"] == ATTEMPT_ID
    assert spawned["lease_id"] == "lease-1"


def test_a_codex_native_that_ends_leaves_both_of_its_streams(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        codex_cli,
        "store_native_diagnostic",
        lambda stdout, stderr, **kwargs: store_native_diagnostic(
            stdout, stderr, state_dir=tmp_path, **kwargs
        ),
    )
    streams = BoundedStreams()
    streams.append(STDOUT, b'{"type":"thread.started"}\n')
    streams.append(STDERR, b"codex refused the resume\n")

    codex_cli._retain(streams, ATTEMPT_ID, 2)

    capture = parse_capture(
        native_diagnostic_path(f"nd-{ATTEMPT_ID}", state_dir=tmp_path).read_bytes()
    )
    assert capture is not None
    assert capture.exit_code == 2
    assert b"thread.started" in capture.stdout
    assert capture.tail == "codex refused the resume"


def test_a_capture_never_grows_with_a_native_that_will_not_stop_talking() -> None:
    streams = BoundedStreams(budget=32)
    streams.append(STDOUT, b"x" * 1000)
    streams.append(STDERR, b"y" * 1000)

    stdout, stderr = streams.snapshot()
    assert len(stdout) == 32 and len(stderr) == 32
