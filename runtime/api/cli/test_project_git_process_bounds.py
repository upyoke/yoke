"""Bounded Git children: pipes drain on every OS and a crossed boundary stops the group."""

from __future__ import annotations

import os
import sys
import time

import pytest

from yoke_cli.config import project_git_process

pytestmark = pytest.mark.windows


@pytest.mark.skipif(os.name != "nt", reason="Windows pipe implementation")
def test_network_git_captures_stdout_and_stderr() -> None:
    result = project_git_process.run_network_git(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ]
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


def test_network_git_captures_output_on_every_platform() -> None:
    result = project_git_process.run_network_git(
        [sys.executable, "-c", "print('ok')"]
    )

    assert (result.returncode, result.stdout.strip()) == (0, "ok")


def test_deadline_stops_the_child_and_its_descendants(tmp_path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"open({str(pid_file)!r}, 'w').write(str(child.pid)); "
        "time.sleep(60)"
    )

    with pytest.raises(project_git_process.NetworkGitBoundaryError, match="deadline"):
        project_git_process.run_network_git(
            [sys.executable, "-c", script], timeout_seconds=3.0
        )

    from yoke_contracts.platform_process import pid_alive

    grandchild = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while pid_alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not pid_alive(grandchild)


def test_output_limit_is_a_named_boundary() -> None:
    with pytest.raises(project_git_process.NetworkGitBoundaryError, match="output limit"):
        project_git_process.run_network_git(
            [sys.executable, "-c", "print('x' * 4096)"], maximum_output_bytes=16
        )
