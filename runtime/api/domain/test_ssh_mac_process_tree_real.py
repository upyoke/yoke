"""The process-tree stop run for real against this machine's own processes.

The SSH transport hands the command to the remote login shell, so each case
runs it through both a POSIX ``sh`` and ``zsh``, the macOS default.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Callable

import pytest

from yoke_harness.ssh_mac_process_tree import stop_process_tree

pytestmark = pytest.mark.skipif(
    not all(Path(tool).exists() for tool in ("/bin/ps", "/usr/bin/pgrep")),
    reason="needs /bin/ps and /usr/bin/pgrep",
)

LOGIN_SHELLS = [
    "/bin/sh",
    pytest.param(
        "/bin/zsh",
        marks=pytest.mark.skipif(not Path("/bin/zsh").exists(), reason="needs zsh"),
    ),
]


def _login_shell(shell: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(command: str, *, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shell, "-c", command], capture_output=True, text=True, timeout=timeout
        )

    return run


def _group(pgid: int) -> list[str]:
    found = subprocess.run(
        ["/usr/bin/pgrep", "-g", str(pgid)], capture_output=True, text=True
    )
    return found.stdout.split()


def _children(pid: int) -> list[str]:
    found = subprocess.run(
        ["/usr/bin/pgrep", "-P", str(pid)], capture_output=True, text=True
    )
    return found.stdout.split()


def _running(pids: list[str]) -> list[str]:
    stats = subprocess.run(
        ["/bin/ps", "-o", "pid=,stat=", "-p", ",".join(pids)],
        capture_output=True,
        text=True,
    )
    return [
        p
        for p, s in (line.split() for line in stats.stdout.splitlines())
        if s[0] != "Z"
    ]


def _start_tree() -> subprocess.Popen[bytes]:
    # The subshell exits at once, so its sleep is re-parented away from the
    # tree while staying in the leader's process group.
    leader = subprocess.Popen(
        ["/bin/sh", "-c", "(/bin/sleep 300 &); exec /bin/sleep 300"],
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while True:
        found = subprocess.run(
            ["/usr/bin/pgrep", "-g", str(leader.pid), "-x", "sleep"],
            capture_output=True, text=True,
        ).stdout.split()
        if len(found) == 2 or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    assert len(found) == 2
    return leader


def _cleanup(leader: subprocess.Popen[bytes]) -> None:
    for pid in _group(leader.pid):
        os.kill(int(pid), 9)
    leader.kill()
    leader.wait()


@pytest.mark.parametrize("shell", LOGIN_SHELLS)
def test_stop_reaches_a_descendant_already_re_parented_out_of_the_tree(
    shell: str,
) -> None:
    leader = _start_tree()
    try:
        stop = stop_process_tree(_login_shell(shell), leader.pid)

        assert stop.stopped, stop
        leader.wait(timeout=10)
        assert _group(leader.pid) == []
    finally:
        _cleanup(leader)


@pytest.mark.parametrize("shell", LOGIN_SHELLS)
def test_stop_reaches_every_process_group_in_the_tree(shell: str) -> None:
    # Job control puts the background sleep in its own process group, so the
    # tree spans two groups and the script loops over more than one PID.
    leader = subprocess.Popen(
        ["/bin/sh", "-c", "set -m; /bin/sleep 300 & exec /bin/sleep 300"],
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while not _children(leader.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    tree = [str(leader.pid), *_children(leader.pid)]
    try:
        assert len(tree) == 2

        stop = stop_process_tree(_login_shell(shell), leader.pid)

        assert stop.stopped, stop
        leader.wait(timeout=10)
        assert _running(tree) == []
    finally:
        for pid in _running(tree):
            os.kill(int(pid), 9)
        leader.kill()
        leader.wait()


@pytest.mark.parametrize("shell", LOGIN_SHELLS)
def test_a_failing_process_listing_reports_survivors_instead_of_stopped(
    shell: str,
) -> None:
    leader = _start_tree()
    run = _login_shell(shell)

    def run_without_ps_listing(command: str, *, timeout: int):
        return run(command.replace("/bin/ps -A", "/usr/bin/false"), timeout=timeout)

    try:
        stop = stop_process_tree(run_without_ps_listing, leader.pid)

        assert not stop.stopped, stop
        assert leader.pid in stop.survivors, stop
    finally:
        _cleanup(leader)
