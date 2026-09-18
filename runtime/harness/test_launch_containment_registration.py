"""Registration retires containment, and a sweep that fires anyway says so.

Containment exists for the gap between starting a native and that native
registering. It used to close only when the launch instruction rendered,
which is a stricter fact than registration and does not always happen: a
launch closed ``registered_and_claimed`` at its deadline reaches a live
worker without rendering anything. One such worker -- registered, holding
its item claim, working -- was terminated at the registration deadline plus
the sweep's grace, and the fleet showed nothing but an idle holder.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from yoke_harness.hooks.launch_context import settle_projection
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)
from yoke_harness.session_launch_containment_sweep import (
    CONTAINMENT_TTL_SECONDS,
    contain_stranded_launch_natives,
)
from yoke_harness.session_launch_handoff import LaunchProjection
from yoke_harness.session_launch_handles import native_handle_path
from yoke_harness.session_relay_termination import adopt_launched_session


LAUNCH_ID = "33333333-3333-4333-8333-333333333333"
SESSION_ID = "44444444-4444-4444-8444-444444444444"


def _sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _record(state_dir: Path | None, pid: int) -> Path:
    """Record one supervised native, reading its path back the way callers do.

    ``state_dir`` of ``None`` is the machine cache the hook and the sweep both
    resolve by default; composing that path by hand is the drift the handle
    directory's own resolver exists to prevent.
    """
    assert record_supervised_native(
        LAUNCH_ID,
        pid,
        native_session_id=SESSION_ID,
        state_dir=state_dir,
    )
    return supervision_record_path(LAUNCH_ID, state_dir)


def test_a_hook_that_proves_registration_retires_containment() -> None:
    """The weaker fact is the one containment is about.

    This hook renders no instruction, which is exactly the shape that used to
    leave the record behind: registration without delivery.
    """
    process = _sleeper()
    try:
        record = _record(None, process.pid)
        assert record.exists()

        settle_projection("no mandate in this output", LaunchProjection(
            LAUNCH_ID, SESSION_ID
        ))

        assert not record.exists()
        # The handle replaces it, so liveness can still reach this native.
        assert native_handle_path(LAUNCH_ID).is_file()
    finally:
        process.kill()
        process.wait()


def test_an_unbound_projection_retires_nothing() -> None:
    """No binding is no registration, so the native stays contained.

    A native still coming up is the case containment was written for, and
    must not be spared by a hook that cannot name a session.
    """
    process = _sleeper()
    try:
        record = _record(None, process.pid)

        settle_projection("no mandate", LaunchProjection(LAUNCH_ID, None))

        assert record.exists()
    finally:
        process.kill()
        process.wait()


def test_the_sweep_spares_a_launch_whose_native_registered(tmp_path: Path) -> None:
    """The backstop: a handle is this machine's own proof of registration.

    Even past the deadline, a record whose launch bound a session names a
    native with authority. The record is stale rather than actionable, so it
    is dropped instead of acted on -- and the process is left alone.
    """
    process = _sleeper()
    try:
        record = _record(tmp_path, process.pid)
        assert adopt_launched_session(LAUNCH_ID, SESSION_ID, state_dir=tmp_path)
        expired = record.stat().st_mtime + CONTAINMENT_TTL_SECONDS + 1

        outcomes = contain_stranded_launch_natives(state_dir=tmp_path, now=expired)

        assert outcomes == []
        assert not record.exists()
        assert process.poll() is None, "a registered native must not be reaped"
    finally:
        process.kill()
        process.wait()


def test_the_sweep_still_reaps_a_native_that_never_registered(tmp_path: Path) -> None:
    """The backstop spares; it must never condemn, and never excuse.

    Without a handle there is no proof of registration, so the original
    behaviour stands: the native is contained.
    """
    process = _sleeper()
    try:
        record = _record(tmp_path, process.pid)
        expired = record.stat().st_mtime + CONTAINMENT_TTL_SECONDS + 1

        outcomes = contain_stranded_launch_natives(state_dir=tmp_path, now=expired)

        assert [outcome.launch_id for outcome in outcomes] == [LAUNCH_ID]
        assert outcomes[0].reason == "registration_timeout"
        assert not record.exists()
    finally:
        process.kill()
        process.wait()
