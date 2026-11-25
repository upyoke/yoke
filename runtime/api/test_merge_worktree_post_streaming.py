"""Streaming primitive tests for merge-worktree's _run_streaming.

run_tests integration tests live in test_merge_worktree_post_runtests.py.
Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from runtime.api.merge_worktree_full_test_support import WORKTREE_ROOT
from yoke_contracts.platform_process import pid_alive


class TestStreamingTestOutput:
    """Verify _run_streaming and the run_tests() streaming integration."""

    def test_streaming_captures_incremental_output(self, tmp_path: Path) -> None:
        """Transcript is retained for a successful streaming run."""
        from yoke_core.engines.merge_worktree_tests import _run_streaming

        rc, transcript = _run_streaming(
            [sys.executable, "-c", "print('line1'); print('line2'); print('line3')"],
            cwd=tmp_path,
            timeout=10,
        )
        assert rc == 0
        assert "line1" in transcript
        assert "line2" in transcript
        assert "line3" in transcript

    @pytest.mark.parametrize("_iteration", range(20))
    def test_streaming_emits_before_process_exit(
        self, tmp_path: Path, _iteration: int
    ) -> None:
        """First streamed output arrives before the subprocess exits."""
        driver = tmp_path / "stream_driver.py"
        driver.write_text(textwrap.dedent(f"""\
            import sys
            from yoke_core.engines.merge_worktree_tests import _run_streaming

            rc, _ = _run_streaming(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('first', flush=True); sys.stdin.readline(); print('second', flush=True)",
                ],
                cwd={str(tmp_path)!r},
                timeout=10,
            )
            print(f"rc={{rc}}", flush=True)
        """))

        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            os.pathsep.join((str(WORKTREE_ROOT), pythonpath)) if pythonpath else str(WORKTREE_ROOT)
        )

        proc = subprocess.Popen(
            [sys.executable, str(driver)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        try:
            first_line = proc.stdout.readline().strip()
            assert first_line == "[tests] first"
            assert proc.poll() is None
            proc.stdin.write("\n")
            proc.stdin.close()
            proc.stdin = None
            remainder = proc.communicate(timeout=10)[0]
            assert "[tests] second" in remainder
            assert "rc=0" in remainder
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_streaming_prefix_on_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Each streamed line is prefixed with [tests]."""
        from yoke_core.engines.merge_worktree_tests import _run_streaming

        _run_streaming(
            [sys.executable, "-c", "print('hello')"],
            cwd=tmp_path,
            timeout=10,
            prefix="[tests]",
        )
        captured = capsys.readouterr()
        assert "[tests] hello" in captured.out

    def test_streaming_custom_prefix(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Prefix is configurable (used for phase banners)."""
        from yoke_core.engines.merge_worktree_tests import _run_streaming

        _run_streaming(
            [sys.executable, "-c", "print('hi')"],
            cwd=tmp_path,
            timeout=10,
            prefix="[custom]",
        )
        captured = capsys.readouterr()
        assert "[custom] hi" in captured.out

    def test_streaming_nonzero_exit_returns_transcript(self, tmp_path: Path) -> None:
        """Transcript available on non-zero exit for failure report."""
        from yoke_core.engines.merge_worktree_tests import _run_streaming

        rc, transcript = _run_streaming(
            [sys.executable, "-c", "print('failure_detail'); raise SystemExit(1)"],
            cwd=tmp_path,
            timeout=10,
        )
        assert rc == 1
        assert "failure_detail" in transcript

    def test_streaming_timeout_terminates_cleanly(self, tmp_path: Path) -> None:
        """Timeout returns -1 and terminates the subprocess tree."""
        from yoke_core.engines.merge_worktree_tests import _run_streaming

        child_pid_path = tmp_path / "child.pid"
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
            cwd=tmp_path,
            timeout=1,
        )
        assert rc == -1
        assert "started" in transcript
        child_pid = int(child_pid_path.read_text())

        deadline = time.monotonic() + 2
        while True:
            if not pid_alive(child_pid):
                break
            if time.monotonic() >= deadline:
                pytest.fail(
                    f"child process {child_pid} survived streaming timeout cleanup"
                )
            time.sleep(0.05)

    def test_streaming_stderr_merged_into_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Stderr output also streams through the prefix."""
        from yoke_core.engines.merge_worktree_tests import _run_streaming

        rc, transcript = _run_streaming(
            [sys.executable, "-c", "import sys; print('out_line'); print('err_line', file=sys.stderr)"],
            cwd=tmp_path,
            timeout=10,
        )
        assert rc == 0
        assert "out_line" in transcript
        assert "err_line" in transcript
        captured = capsys.readouterr()
        assert "[tests] out_line" in captured.out
        assert "[tests] err_line" in captured.out
