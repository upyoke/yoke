"""Tests for whole-tree process reaping.

These exercise real processes rather than mocks: the behavior under test is
whether a GRANDCHILD survives, and a mock cannot leak a process. Each case
spawns a shell that starts a background sleeper, then asserts the sleeper is
gone once the helper has finished — the sleeper stands in for an xdist worker
holding a test database open.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time

import psutil
import pytest

from yoke_core.domain import process_group_reaping

# A real grandchild retains the inherited pipes until the reaper stops it.
_SPAWN_GRANDCHILD_THEN_BLOCK = (
    "import pathlib, subprocess, sys, time; "
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
    "time.sleep(60)"
)


def _process_is_alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _wait_until_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_alive(pid):
            return True
        time.sleep(0.05)
    return not _process_is_alive(pid)


def _wait_for_nonempty_text(path, timeout: float = 10.0) -> str:
    """Wait for file content, not mere existence.

    ``Path.write_text`` creates then writes, so ``exists()`` can observe
    the empty window between those steps.
    """
    deadline = time.monotonic() + timeout
    observed = ""
    while time.monotonic() < deadline:
        try:
            observed = path.read_text()
        except FileNotFoundError:
            observed = ""
        if observed.strip():
            return observed
        time.sleep(0.05)
    return observed


def _kill_if_alive(pid: int) -> None:
    try:
        psutil.Process(pid).kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def test_terminate_reaches_grandchildren_not_just_the_direct_child(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    proc = process_group_reaping.popen_in_process_group(
        [sys.executable, "-c", _SPAWN_GRANDCHILD_THEN_BLOCK, str(pid_file)]
    )
    grandchild_pid = int(_wait_for_nonempty_text(pid_file))
    try:
        assert _process_is_alive(grandchild_pid)

        process_group_reaping.terminate_process_group(proc)

        assert proc.poll() is not None
        assert _wait_until_gone(grandchild_pid)
    finally:
        _kill_if_alive(grandchild_pid)
        process_group_reaping.terminate_process_group(proc)


def test_timeout_reaps_the_whole_tree_before_raising(tmp_path):
    # subprocess.run's own timeout kills only the shell, leaving the work it
    # started alive — which is how an abandoned run keeps holding databases.
    pid_file = tmp_path / "grandchild.pid"

    with pytest.raises(subprocess.TimeoutExpired):
        process_group_reaping.run_in_process_group(
            [sys.executable, "-c", _SPAWN_GRANDCHILD_THEN_BLOCK, str(pid_file)],
            capture_output=True,
            text=True,
            timeout=3.0,
            grace_seconds=2.0,
        )

    grandchild_pid = int(_wait_for_nonempty_text(pid_file).strip())
    try:
        assert _wait_until_gone(grandchild_pid)
    finally:
        _kill_if_alive(grandchild_pid)


@pytest.mark.posix_only(reason="starts a descendant with setsid outside the original POSIX process group")
def test_reaping_reaches_a_grandchild_that_started_its_own_session(tmp_path):
    """Nested isolation must not put a descendant out of reach.

    A runner launched under a supervisor puts its own child in a fresh session
    so that IT can reap precisely — but a new session is unreachable from the
    supervisor's killpg. Observed live: a QA command timed out, its group was
    reaped, and the inner pytest survived 21 minutes holding its databases
    open. The reaper must therefore follow parent links, not only the group.
    """
    pid_file = tmp_path / "detached.pid"
    # The middle process mimics a runner: it puts its own child in a new
    # session, so only a descendant walk can find that child.
    middle = (
        "import os, pathlib, subprocess, time\n"
        "child = subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(300)\n"
    )
    proc = process_group_reaping.popen_in_process_group([sys.executable, "-c", middle])
    detached_pid = int(_wait_for_nonempty_text(pid_file).strip())
    try:
        assert _process_is_alive(detached_pid)

        process_group_reaping.terminate_process_group(proc)

        assert _wait_until_gone(detached_pid)
    finally:
        _kill_if_alive(detached_pid)


def test_run_in_process_group_returns_completed_process_on_success():
    completed = process_group_reaping.run_in_process_group(
        [sys.executable, "-c", "import sys; sys.stdout.write('hello')"],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == "hello"


@pytest.mark.parametrize(
    "signal_number",
    [
        signal.SIGINT,
        signal.SIGTERM,
        pytest.param(
            getattr(signal, "SIGHUP", None),
            marks=pytest.mark.posix_only(reason="Windows does not deliver terminal-close SIGHUP"),
        ),
    ],
)
def test_signal_during_guarded_block_reaps_then_raises(signal_number, tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    proc = process_group_reaping.popen_in_process_group(
        [sys.executable, "-c", _SPAWN_GRANDCHILD_THEN_BLOCK, str(pid_file)]
    )
    grandchild_pid = int(_wait_for_nonempty_text(pid_file))
    try:
        with pytest.raises(process_group_reaping.ProcessGroupInterrupted) as caught:
            with process_group_reaping.interruption_reaps_process_group(proc):
                signal.raise_signal(signal_number)
                time.sleep(0.05)

        assert caught.value.signal_number == signal_number
        assert _wait_until_gone(grandchild_pid)
    finally:
        _kill_if_alive(grandchild_pid)
        process_group_reaping.terminate_process_group(proc)


def test_guard_restores_prior_signal_handlers():
    previous = signal.getsignal(signal.SIGTERM)
    proc = process_group_reaping.popen_in_process_group([sys.executable, "-c", "raise SystemExit(0)"])
    try:
        with process_group_reaping.interruption_reaps_process_group(proc):
            assert signal.getsignal(signal.SIGTERM) is not previous
    finally:
        proc.wait()

    assert signal.getsignal(signal.SIGTERM) is previous


def test_exception_in_guarded_block_still_reaps(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    proc = process_group_reaping.popen_in_process_group(
        [sys.executable, "-c", _SPAWN_GRANDCHILD_THEN_BLOCK, str(pid_file)]
    )
    grandchild_pid = int(_wait_for_nonempty_text(pid_file))
    try:
        with pytest.raises(RuntimeError):
            with process_group_reaping.interruption_reaps_process_group(proc):
                raise RuntimeError("reader loop blew up")

        assert _wait_until_gone(grandchild_pid)
    finally:
        _kill_if_alive(grandchild_pid)
        process_group_reaping.terminate_process_group(proc)


def test_terminate_is_safe_on_an_already_finished_child():
    proc = process_group_reaping.popen_in_process_group([sys.executable, "-c", "raise SystemExit(3)"])
    proc.wait()

    process_group_reaping.terminate_process_group(proc)

    assert proc.returncode == 3
