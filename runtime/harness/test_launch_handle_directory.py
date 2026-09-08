"""One machine-wide directory carries a launch handle from writer to readers.

The hook that writes a launch handle runs inside the launched session and
resolves the machine cache; the relay that reads it runs with its own state
directory, keyed by the control-plane connection it serves. When the handle
directory was composed from whichever root the caller passed, those two roots
were different — the native's exit went unreported and its usage never landed.
Every test here writes through the hook's default and reads through an
explicitly different relay state directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from yoke_contracts.process_ancestry import process_start_time
from yoke_harness.session_launch_containment import record_supervised_native
from yoke_harness import session_launch_handles
from yoke_harness.session_launch_handles import (
    NATIVE_HANDLE_DIRECTORY_NAME,
    native_handle_path,
)
from yoke_harness.session_relay_process_liveness import (
    report_verified_dead_sessions,
    verified_dead_sessions,
)
from yoke_harness.session_relay_termination import (
    adopt_launched_session,
    reap_terminated_session,
)


#: Captured before the per-test guard replaces it, so one test can still
#: prove what the unpatched resolver binds to.
MACHINE_CACHE_RESOLVER = session_launch_handles.native_handle_directory

LAUNCH_ID = "55555555-5555-4555-8555-555555555555"
SESSION_ID = "66666666-6666-4666-8666-666666666666"


class _Inventory:
    relay_id = "machine:test"
    machine_id = "machine-1"
    project_ids = (1,)


class _Response:
    def __init__(self, result: dict) -> None:
        self.success = True
        self.result = result
        self.error = None


class _Dispatcher:
    def __init__(self, ended: list[str]) -> None:
        self.calls: list[dict] = []
        self._response = _Response({"ended": ended, "skipped": []})

    def __call__(self, *, function_id, target, payload, timeout_s):
        del target, timeout_s
        self.calls.append({"function_id": function_id, **payload})
        return self._response


def _relay_state(tmp_path: Path) -> Path:
    """A relay state directory that is deliberately not the machine cache."""
    state = tmp_path / "relay-state"
    state.mkdir(parents=True, exist_ok=True)
    return state


def _hook_written_handle(pid: int) -> bool:
    """Write custody exactly as the launched session's own hook does."""
    assert record_supervised_native(LAUNCH_ID, pid)
    return adopt_launched_session(LAUNCH_ID, SESSION_ID)


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def test_a_hook_written_handle_is_read_by_a_relay_with_its_own_state_dir(
    tmp_path: Path,
) -> None:
    assert _hook_written_handle(os.getpid())

    dead = verified_dead_sessions(
        state_dir=_relay_state(tmp_path),
        anchors_dir=tmp_path / "anchors",
        # A reused pid names a different process, so this native reads as gone.
        start_time_of=lambda _pid: "some-other-start",
    )

    assert [entry.session_id for entry in dead] == [SESSION_ID]
    assert dead[0].evidence["launch_id"] == LAUNCH_ID


def test_a_live_hook_written_handle_is_not_reported_dead(tmp_path: Path) -> None:
    assert _hook_written_handle(os.getpid())

    dead = verified_dead_sessions(
        state_dir=_relay_state(tmp_path),
        anchors_dir=tmp_path / "anchors",
        start_time_of=process_start_time,
    )

    assert dead == ()


def test_a_landed_report_prunes_the_hook_written_handle(tmp_path: Path) -> None:
    assert _hook_written_handle(os.getpid())
    dispatcher = _Dispatcher([SESSION_ID])

    ended = report_verified_dead_sessions(
        dispatcher,
        _Inventory(),
        state_dir=_relay_state(tmp_path),
        anchors_dir=tmp_path / "anchors",
        start_time_of=lambda _pid: None,
    )

    assert ended == (SESSION_ID,)
    assert not native_handle_path(LAUNCH_ID).exists()


def test_a_relay_with_its_own_state_dir_terminates_a_hook_written_handle(
    tmp_path: Path, monkeypatch
) -> None:
    process = _sleeper()
    monkeypatch.setattr(
        "yoke_harness.session_relay_termination.TERMINATE_WAIT_SECONDS",
        0.05,
    )
    try:
        assert _hook_written_handle(process.pid)

        result = reap_terminated_session(
            {
                "job_kind": "terminate",
                "job_id": SESSION_ID,
                "target_session_id": SESSION_ID,
                "target_launch_id": LAUNCH_ID,
            },
            state_dir=_relay_state(tmp_path),
        )

        assert result.result_code in {"terminated", "killed"}
        assert result.evidence["handles_considered"] == 1
        process.wait(timeout=5)
        assert not native_handle_path(LAUNCH_ID).exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_the_directory_is_the_machine_cache_and_owner_only(
    tmp_path: Path, monkeypatch
) -> None:
    """The unpatched resolver reads the machine cache, not a relay state dir."""
    from yoke_cli.config import machine_config

    cache = tmp_path / "machine-cache"
    monkeypatch.setattr(machine_config, "cache_dir", lambda _path=None: cache)
    monkeypatch.setattr(
        session_launch_handles, "native_handle_directory", MACHINE_CACHE_RESOLVER
    )

    assert _hook_written_handle(os.getpid())
    path = native_handle_path(LAUNCH_ID)

    assert path.parent == cache / NATIVE_HANDLE_DIRECTORY_NAME
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(path.read_text())["target_session_id"] == SESSION_ID
