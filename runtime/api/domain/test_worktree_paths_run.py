"""``worktree_paths._run`` keeps launch failures and timeouts in stderr."""

from __future__ import annotations

import subprocess
import sys

from yoke_core.domain.worktree_paths import _run, captured_process_detail


def test_file_not_found_surfaces_in_stderr() -> None:
    proc = _run(["definitely_not_a_real_command_xyz_2412"])
    assert proc.returncode == 1
    assert "FileNotFoundError" in proc.stderr
    assert "definitely_not_a_real_command_xyz_2412" in proc.stderr


def test_timeout_surfaces_exception_and_captured_stderr() -> None:
    proc = _run(
        [
            sys.executable,
            "-c",
            "import sys, time; sys.stderr.write('partial git\\n'); "
            "sys.stderr.flush(); time.sleep(5)",
        ],
        timeout=0.2,
    )
    assert proc.returncode == 1
    assert "TimeoutExpired" in proc.stderr
    assert "partial git" in proc.stderr


def test_captured_process_detail_falls_back_to_stdout() -> None:
    proc = subprocess.CompletedProcess(["git"], 1, stdout="fatal: boom\n", stderr="")
    assert captured_process_detail(proc) == "fatal: boom"


def test_captured_process_detail_marks_empty_output() -> None:
    proc = subprocess.CompletedProcess(["git"], 1, stdout="", stderr="")
    assert captured_process_detail(proc) == "(no git output)"
