"""Resumed delivery: a follower re-armed against a capture it has served.

A wake loop re-arms the same subscription every few minutes. Replaying
the capture each time hands the reader its own backlog over and over, so
delivery is recorded and a later pass serves only what is new. Covered
here: the resume itself, the sentinel a completed capture must still
report, the two markers that must fall back to serving the capture
whole, and the writer binding a skipped header must still establish.
"""

from __future__ import annotations

import io
from pathlib import Path

from yoke_core.tools import _watch_capture_binding as binding
from yoke_core.tools import watch_tail

SENTINEL = "# watch_pytest exit=0 raw=/tmp/raw.log\n"
DEAD_PID = 2**31 - 1


def _stamped(progress: Path, kind: str = "pytest", pid: int | None = None) -> None:
    """Claim *progress* for *pid* the way a bound watcher run does."""
    progress.write_text(
        binding.writer_marker_line(kind, pid=pid), encoding="utf-8"
    )


class _ClosingStream:
    """A reader that goes away mid-stream, the way an expiring wake does."""

    def __init__(self, accept: int) -> None:
        self.accept = accept
        self.text = ""

    def write(self, line: str) -> None:
        if self.accept <= 0:
            raise BrokenPipeError(32, "Broken pipe")
        self.accept -= 1
        self.text += line

    def flush(self) -> None:
        return None


def _served(progress: Path, **kwargs) -> str:
    """One follower pass over *progress*, returning what it forwarded."""
    out = io.StringIO()
    watch_tail.follow(progress, out=out, poll_interval=0.01, **kwargs)
    return out.getvalue()


def test_a_re_armed_follower_resumes_instead_of_replaying(
    tmp_path: Path,
) -> None:
    """The wake-loop case: each re-arm hands the reader only new lines.

    The first reader leaves mid-capture, which is exactly what an
    expiring wake does -- and the line it never received must still be
    waiting for the next one.
    """
    progress = tmp_path / "progress.log"
    _stamped(progress)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("COPY tenant_1: starting\n")
        handle.write("COPY tenant_2: starting\n")

    closing = _ClosingStream(accept=2)
    assert watch_tail.follow(progress, out=closing, poll_interval=0.01) == 0

    with progress.open("a", encoding="utf-8") as handle:
        handle.write("COPY tenant_3: starting\n")
        handle.write(SENTINEL)

    second = _served(progress)

    assert "tenant_1" in closing.text
    # Delivered lines are not sent again; the one the closed reader never
    # received is, because the marker only advances on a served line.
    assert "tenant_1" not in second
    assert "tenant_2" in second
    assert "tenant_3" in second
    assert SENTINEL in second


def test_a_completed_capture_still_reports_its_sentinel(tmp_path: Path) -> None:
    """Re-arming after the end must not hang waiting on a served sentinel."""
    progress = tmp_path / "progress.log"
    _stamped(progress)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("only line\n")
        handle.write(SENTINEL)

    first = _served(progress)
    second = _served(progress)

    assert "only line" in first
    assert "only line" not in second
    assert SENTINEL in second


def test_a_shorter_capture_under_the_same_name_is_served_whole(
    tmp_path: Path,
) -> None:
    """A fresh run reusing the path faces a reader that has seen nothing."""
    progress = tmp_path / "progress.log"
    _stamped(progress)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("first run line\n")
        handle.write("second run line\n")
        handle.write(SENTINEL)
    _served(progress)

    _stamped(progress)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("second run only line\n")
        handle.write(SENTINEL)

    assert "second run only line" in _served(progress)


def test_an_unreadable_marker_replays_rather_than_skips(tmp_path: Path) -> None:
    """Noise beats silence: a marker nobody can parse serves the capture."""
    progress = tmp_path / "progress.log"
    _stamped(progress)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("progress line\n")
        handle.write(SENTINEL)
    watch_tail.delivered_marker(progress).write_text(
        "not-a-number", encoding="utf-8"
    )

    assert "progress line" in _served(progress)


def test_a_resumed_follower_still_learns_the_writer(tmp_path: Path) -> None:
    """The pid header binds the wait even on a pass that does not re-send it.

    Writer identity is what bounds the follow, so a resumed follower that
    skipped the header as already-delivered would wait forever on a
    capture whose writer is gone.
    """
    progress = tmp_path / "progress.log"
    _stamped(progress, pid=DEAD_PID)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("[ 12%] partial progress\n")
    _served(progress, grace_seconds=5.0)

    out = io.StringIO()
    rc = watch_tail.follow(
        progress, out=out, poll_interval=0.01, grace_seconds=5.0
    )

    assert rc == binding.UNWRITTEN_CAPTURE_EXIT
    assert f"watcher pid {DEAD_PID}" in out.getvalue()
