"""Tests for :mod:`yoke_core.tools.watch_tail`.

Covers the follow cases:

- exits cleanly when the watcher exit sentinel is already present at
  invocation (the "already-complete file" case),
- forwards each line and exits when the sentinel arrives mid-stream
  from a slow producer,
- waits for a missing file to appear, then reads it from the
  beginning,
- the CLI ``python3 -m yoke_core.tools.watch_tail`` exits cleanly
  on a pre-populated file via subprocess (smoke test for the entry
  point that ``print_streaming_pair`` will hand the operator),

plus the writer-evidence refusals: a capture no watcher ever claimed,
a capture whose claiming watcher died before its sentinel, and the two
non-regressions those must not break -- a claimed but slow-starting run
and a sentinel written in the instant before the writer exited.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from yoke_core.tools import _watch_capture_binding as binding
from yoke_core.tools import watch_tail


def test_exits_when_sentinel_already_present(tmp_path: Path) -> None:
    progress = tmp_path / "progress.log"
    progress.write_text(
        "first progress line\n"
        "second progress line\n"
        "# watch_pytest exit=0 raw=/tmp/raw.log\n",
        encoding="utf-8",
    )
    out = io.StringIO()

    rc = watch_tail.follow(progress, out=out, poll_interval=0.01)
    text = out.getvalue()

    assert rc == 0
    assert "first progress line" in text
    assert "second progress line" in text
    # The sentinel itself is forwarded so a human reading the Monitor
    # output still sees the watcher exit record.
    assert "# watch_pytest exit=0 raw=/tmp/raw.log" in text


def test_exits_on_negative_exit_sentinel(tmp_path: Path) -> None:
    """A signal-killed child writes a negative rc (e.g. SIGTERM -> -15)."""
    progress = tmp_path / "progress.log"
    progress.write_text(
        "progress before kill\n"
        "# watch_pytest exit=-15 raw=/tmp/raw.log\n",
        encoding="utf-8",
    )
    out = io.StringIO()

    rc = watch_tail.follow(progress, out=out, poll_interval=0.01)
    text = out.getvalue()

    assert rc == 0
    assert "progress before kill" in text
    assert "# watch_pytest exit=-15" in text


def test_follows_slow_producer(tmp_path: Path) -> None:
    progress = tmp_path / "progress.log"
    progress.write_text("", encoding="utf-8")

    def producer() -> None:
        time.sleep(0.05)
        with progress.open("a", encoding="utf-8") as handle:
            handle.write("progress 1\n")
            handle.flush()
            time.sleep(0.05)
            handle.write("progress 2\n")
            handle.flush()
            time.sleep(0.05)
            handle.write("# watch_merge exit=2 raw=/tmp/raw.log\n")
            handle.flush()

    thread = threading.Thread(target=producer)
    thread.start()
    out = io.StringIO()
    try:
        rc = watch_tail.follow(progress, out=out, poll_interval=0.01)
    finally:
        thread.join(timeout=2.0)

    text = out.getvalue()
    assert rc == 0
    assert "progress 1" in text
    assert "progress 2" in text
    assert "# watch_merge exit=2" in text


def test_waits_for_missing_file(tmp_path: Path) -> None:
    progress = tmp_path / "not-yet.log"

    def creator() -> None:
        time.sleep(0.1)
        progress.write_text(
            "delayed progress\n"
            "# watch_pytest exit=0 raw=/tmp/raw.log\n",
            encoding="utf-8",
        )

    thread = threading.Thread(target=creator)
    thread.start()
    out = io.StringIO()
    try:
        rc = watch_tail.follow(progress, out=out, poll_interval=0.01)
    finally:
        thread.join(timeout=2.0)

    text = out.getvalue()
    assert rc == 0
    assert "delayed progress" in text
    assert "# watch_pytest exit=0" in text


def test_cli_subprocess_exits_cleanly(tmp_path: Path) -> None:
    progress = tmp_path / "progress.log"
    progress.write_text(
        "subprocess line\n# watch_pytest exit=0 raw=/tmp/raw.log\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    yoke_root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = (
        f"{yoke_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.tools.watch_tail",
            str(progress),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert result.returncode == 0, (
        f"watch_tail CLI failed (exit={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "subprocess line" in result.stdout
    assert "# watch_pytest exit=0" in result.stdout


def _stamped(progress: Path, kind: str = "pytest", pid: int | None = None) -> None:
    """Claim *progress* for *pid* the way a bound watcher run does."""
    progress.write_text(
        binding.writer_marker_line(kind, pid=pid), encoding="utf-8"
    )


def test_refuses_a_capture_no_watcher_ever_claimed(tmp_path: Path) -> None:
    """The observed failure: an empty capture followed for 29 minutes."""
    progress = tmp_path / "progress.log"
    progress.write_text("", encoding="utf-8")
    out = io.StringIO()

    rc = watch_tail.follow(
        progress, out=out, poll_interval=0.01, grace_seconds=0.05
    )
    text = out.getvalue()

    assert rc == binding.UNWRITTEN_CAPTURE_EXIT
    assert "no watcher claimed" in text
    assert "--raw-capture/--progress-capture" in text


def test_refuses_when_the_capture_never_appears(tmp_path: Path) -> None:
    out = io.StringIO()

    rc = watch_tail.follow(
        tmp_path / "never-created.log",
        out=out,
        poll_interval=0.01,
        grace_seconds=0.05,
    )

    assert rc == binding.UNWRITTEN_CAPTURE_EXIT
    assert "--print-streaming-pair" in out.getvalue()


def test_refuses_when_the_claiming_watcher_died_without_a_sentinel(
    tmp_path: Path,
) -> None:
    progress = tmp_path / "progress.log"
    dead_pid = 2**31 - 1
    _stamped(progress, pid=dead_pid)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("[ 12%] partial progress\n")
    out = io.StringIO()

    rc = watch_tail.follow(
        progress, out=out, poll_interval=0.01, grace_seconds=5.0
    )
    text = out.getvalue()

    assert rc == binding.UNWRITTEN_CAPTURE_EXIT
    assert "[ 12%] partial progress" in text
    assert f"watcher pid {dead_pid}" in text


def test_a_claimed_capture_survives_a_slow_start(tmp_path: Path) -> None:
    """A queued run stamps immediately and writes much later."""
    progress = tmp_path / "progress.log"
    _stamped(progress)

    def producer() -> None:
        time.sleep(0.15)
        with progress.open("a", encoding="utf-8") as handle:
            handle.write("[ 99%] finally started\n")
            handle.write("# watch_pytest exit=0 raw=/tmp/raw.log\n")
            handle.flush()

    thread = threading.Thread(target=producer)
    thread.start()
    out = io.StringIO()
    try:
        # The grace window has long since passed by the time content
        # arrives; the live marker is what keeps the follow going.
        rc = watch_tail.follow(
            progress, out=out, poll_interval=0.01, grace_seconds=0.01
        )
    finally:
        thread.join(timeout=2.0)

    assert rc == 0
    assert "[ 99%] finally started" in out.getvalue()


def test_a_sentinel_written_just_before_the_writer_exited_still_exits_zero(
    tmp_path: Path,
) -> None:
    """Liveness is read before the final drain, so this is not a refusal."""
    progress = tmp_path / "progress.log"
    _stamped(progress, pid=2**31 - 1)
    with progress.open("a", encoding="utf-8") as handle:
        handle.write("# watch_pytest exit=0 raw=/tmp/raw.log\n")
    out = io.StringIO()

    rc = watch_tail.follow(
        progress, out=out, poll_interval=0.01, grace_seconds=5.0
    )

    assert rc == 0
    assert "# watch_pytest exit=0" in out.getvalue()
