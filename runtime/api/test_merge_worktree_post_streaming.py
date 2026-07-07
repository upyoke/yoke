"""Streaming primitive tests for merge-worktree's _run_streaming.

run_tests integration tests live in test_merge_worktree_post_runtests.py.
Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from runtime.api.test_merge_worktree_full import (
    WORKTREE_ROOT,
)


class TestStreamingTestOutput:
    """Verify _run_streaming and the run_tests() streaming integration."""

    def test_streaming_captures_incremental_output(self) -> None:
        """AC-4: Transcript is retained for a successful streaming run."""
        from yoke_core.engines.merge_worktree import _run_streaming

        rc, transcript = _run_streaming(
            ["sh", "-c", "echo line1; echo line2; echo line3"],
            cwd="/tmp",
            timeout=10,
        )
        assert rc == 0
        assert "line1" in transcript
        assert "line2" in transcript
        assert "line3" in transcript

    def test_streaming_emits_before_process_exit(self, tmp_path: Path) -> None:
        """AC-1: First streamed output arrives before the subprocess exits."""
        driver = tmp_path / "stream_driver.py"
        driver.write_text(textwrap.dedent("""\
            import os
            import sys
            from yoke_core.engines.merge_worktree import _run_streaming

            rc, _ = _run_streaming(
                [
                    sys.executable,
                    "-c",
                    "import time; print('first', flush=True); time.sleep(2); print('second', flush=True)",
                ],
                cwd="/tmp",
                timeout=10,
            )
            print(f"rc={rc}", flush=True)
        """))

        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{WORKTREE_ROOT}:{pythonpath}" if pythonpath else str(WORKTREE_ROOT)
        )

        proc = subprocess.Popen(
            [sys.executable, str(driver)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert proc.stdout is not None
        try:
            start = time.monotonic()
            first_line = proc.stdout.readline().strip()
            elapsed = time.monotonic() - start
            assert first_line == "[tests] first"
            assert elapsed < 1.5
            assert proc.poll() is None
            remainder = proc.communicate(timeout=10)[0]
            assert "[tests] second" in remainder
            assert "rc=0" in remainder
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_streaming_prefix_on_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """AC-2: Each streamed line is prefixed with [tests]."""
        from yoke_core.engines.merge_worktree import _run_streaming

        _run_streaming(
            ["sh", "-c", "echo hello"],
            cwd="/tmp",
            timeout=10,
            prefix="[tests]",
        )
        captured = capsys.readouterr()
        assert "[tests] hello" in captured.out

    def test_streaming_custom_prefix(self, capsys: pytest.CaptureFixture) -> None:
        """AC-2: Prefix is configurable (used for phase banners)."""
        from yoke_core.engines.merge_worktree import _run_streaming

        _run_streaming(
            ["sh", "-c", "echo hi"],
            cwd="/tmp",
            timeout=10,
            prefix="[custom]",
        )
        captured = capsys.readouterr()
        assert "[custom] hi" in captured.out

    def test_streaming_nonzero_exit_returns_transcript(self) -> None:
        """AC-4: Transcript available on non-zero exit for failure report."""
        from yoke_core.engines.merge_worktree import _run_streaming

        rc, transcript = _run_streaming(
            ["sh", "-c", "echo failure_detail; exit 1"],
            cwd="/tmp",
            timeout=10,
        )
        assert rc == 1
        assert "failure_detail" in transcript

    def test_streaming_timeout_terminates_cleanly(self) -> None:
        """AC-5: Timeout returns -1 and terminates the subprocess tree."""
        from yoke_core.engines.merge_worktree import _run_streaming

        child_pid_path = Path(tempfile.mkdtemp()) / "child.pid"
        parent_code = textwrap.dedent(f"""\
            import pathlib
            import subprocess
            import sys
            import time

            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))
            print("started", flush=True)
            time.sleep(60)
        """)

        rc, transcript = _run_streaming(
            [sys.executable, "-c", parent_code],
            cwd="/tmp",
            timeout=1,
        )
        assert rc == -1
        assert "started" in transcript
        child_pid = int(child_pid_path.read_text())

        deadline = time.monotonic() + 2
        while True:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            if time.monotonic() >= deadline:
                os.kill(child_pid, signal.SIGKILL)
                pytest.fail(
                    f"child process {child_pid} survived streaming timeout cleanup"
                )
            time.sleep(0.05)

    def test_streaming_stderr_merged_into_stdout(self, capsys: pytest.CaptureFixture) -> None:
        """AC-1: stderr output also streams through the prefix."""
        from yoke_core.engines.merge_worktree import _run_streaming

        rc, transcript = _run_streaming(
            ["sh", "-c", "echo out_line; echo err_line >&2"],
            cwd="/tmp",
            timeout=10,
        )
        assert rc == 0
        assert "out_line" in transcript
        assert "err_line" in transcript
        captured = capsys.readouterr()
        assert "[tests] out_line" in captured.out
        assert "[tests] err_line" in captured.out
