"""Tests for how a watched command ends: exit codes and interruption.

Split from the main watcher tests so each file stays within the
authored-file line limit. The interruption cases spawn real processes
rather than mocks: the behavior under test is whether a GRANDCHILD
survives, and a mock cannot leak a process.
"""

from __future__ import annotations

import io
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import (
    Classification,
    LineClass,
    ThrottlePolicy,
)

PASSTHROUGH_POLICY = ThrottlePolicy(
    percent_step=0.0001, min_interval_seconds=0.0001
)


def _python_emit_script(tmp_path: Path, lines: list[str], exit_code: int) -> Path:
    """Write a Python script that prints *lines* and exits with *exit_code*."""
    script = tmp_path / "emit.py"
    body_lines = [
        "import sys",
        "lines = " + repr(lines),
        "for line in lines:",
        "    print(line)",
        f"sys.exit({exit_code})",
    ]
    script.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return script


def _summary_classifier(line: str) -> Classification:
    """Treat MATCH-prefixed lines as SUMMARY (immediate, never throttled)."""
    if line.startswith("MATCH"):
        return Classification(LineClass.SUMMARY)
    return Classification(LineClass.NOISE)


class TestRunWatcherInterruption:
    """An interrupted watcher must reap its children, not orphan them.

    Workers that outlive their watcher keep their test databases open, so the
    next run blocks on databases nobody is using. The watcher owns the child's
    process group precisely so an interruption can take the whole tree down.
    """

    def test_interruption_reaps_the_tree_and_reports_on_every_surface(
        self, tmp_path
    ):
        pid_file = tmp_path / "grandchild.pid"
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()

        def interrupt_once(line: str) -> Classification:
            # Fires while the child is mid-stream, standing in for the SIGTERM
            # a harness sends when it gives up on a run.
            os.kill(os.getpid(), signal.SIGTERM)
            return Classification(LineClass.NOISE)

        rc = _watch_runner.run_watcher(
            argv=[
                "/bin/sh",
                "-c",
                f"sleep 300 & echo $! > {pid_file}; echo started; sleep 300",
            ],
            classifier=interrupt_once,
            raw_capture=raw,
            progress_capture=progress,
            kind="interrupted",
            stdout_stream=stdout,
            policy=PASSTHROUGH_POLICY,
        )

        assert rc == 128 + signal.SIGTERM
        grandchild_pid = int(pid_file.read_text().strip())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(grandchild_pid, 0)

        # An armed follower exits on the sentinel; a silent death is
        # indistinguishable from a run still in progress.
        assert "child process group reaped" in raw.read_text(encoding="utf-8")
        progress_text = progress.read_text(encoding="utf-8")
        assert "child process group reaped" in progress_text
        assert f"# watch_interrupted exit={rc}" in progress_text
        assert "child process group reaped" in stdout.getvalue()



class TestRunWatcherTimeout:
    """A deadline must reap the tree, not just abandon the direct child.

    A registered command runs through a shell, so the work itself is a
    grandchild holding the databases. The timeout path exists so a wedged
    run releases them instead of hanging its caller forever.
    """

    def test_timeout_reaps_the_tree_and_reports_on_every_surface(self, tmp_path):
        pid_file = tmp_path / "grandchild.pid"
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        stdout = io.StringIO()

        rc = _watch_runner.run_watcher(
            argv=[
                "/bin/sh",
                "-c",
                f"sleep 300 & echo $! > {pid_file}; echo started; sleep 300",
            ],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="deadline",
            stdout_stream=stdout,
            policy=PASSTHROUGH_POLICY,
            timeout_seconds=1,
        )

        assert rc == _watch_runner.TIMEOUT_EXIT
        grandchild_pid = int(pid_file.read_text().strip())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(grandchild_pid, 0)

        assert "timed out after 1 seconds" in raw.read_text(encoding="utf-8")
        progress_text = progress.read_text(encoding="utf-8")
        assert "timed out after 1 seconds" in progress_text
        assert f"# watch_deadline exit={rc}" in progress_text
        # A timing-out run must not also claim it is healthily still running.
        assert "still running" not in stdout.getvalue()

    def test_no_deadline_leaves_a_fast_command_untouched(self, tmp_path):
        script = _python_emit_script(tmp_path, ["MATCH done"], exit_code=0)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="nodeadline",
            stdout_stream=io.StringIO(),
            policy=PASSTHROUGH_POLICY,
        )

        assert rc == 0
        assert "timed out" not in progress.read_text(encoding="utf-8")


class TestRunWatcherExitCodePreservation:
    @pytest.mark.parametrize("code", [0, 1, 2, 5, 42])
    def test_propagates_underlying_exit_code(self, tmp_path, code):
        script = _python_emit_script(tmp_path, ["MATCH only"], exit_code=code)
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        rc = _watch_runner.run_watcher(
            argv=[sys.executable, str(script)],
            classifier=_summary_classifier,
            raw_capture=raw,
            progress_capture=progress,
            kind="exitcheck",
            stdout_stream=io.StringIO(),
            policy=PASSTHROUGH_POLICY,
        )
        assert rc == code


