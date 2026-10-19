"""The process-tree stop run for real against this machine's own processes."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

import pytest

from yoke_harness.ssh_mac_process_tree import stop_process_tree

pytestmark = pytest.mark.skipif(
    not all(Path(tool).exists() for tool in ("/bin/ps", "/usr/bin/pgrep")),
    reason="needs /bin/ps and /usr/bin/pgrep",
)


def _run(script: str, *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", script], capture_output=True, text=True, timeout=timeout
    )


def _group(pgid: int) -> list[str]:
    found = subprocess.run(
        ["/usr/bin/pgrep", "-g", str(pgid)], capture_output=True, text=True
    )
    return found.stdout.split()


def test_stop_reaches_a_descendant_already_re_parented_out_of_the_tree() -> None:
    # The subshell exits at once, so its sleep is re-parented away from the
    # tree while staying in the leader's process group.
    leader = subprocess.Popen(
        ["/bin/sh", "-c", "(/bin/sleep 300 &); exec /bin/sleep 300"],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while len(_group(leader.pid)) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(_group(leader.pid)) == 2

        stop = stop_process_tree(_run, leader.pid)

        assert stop.stopped, stop
        leader.wait(timeout=10)
        assert _group(leader.pid) == []
    finally:
        for pid in _group(leader.pid):
            os.kill(int(pid), 9)
        leader.kill()
        leader.wait()
