"""Custody precedes execution, including natives that exit immediately."""

from io import BytesIO
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from yoke_contracts.owner_private_path import create_owner_private_directory
from yoke_harness import session_relay_native_supervisor as supervisor
from yoke_harness.session_relay_native_create import immediate_native_refusal
from yoke_harness.session_relay_native_spawn import spawn_supervised_native
from yoke_harness.session_relay_process_group import spawn_relay_process

pytestmark = pytest.mark.windows


def test_current_native_exit_replaces_the_initialized_capture(tmp_path: Path) -> None:
    tmp_path = create_owner_private_directory(tmp_path / "private-relay")
    reaped = threading.Event()
    processes = []

    def factory(*args, **kwargs):
        process = spawn_relay_process(*args, **kwargs)
        processes.append(process)
        wait = process.wait

        def observed_wait(*args, **kwargs):
            result = wait(*args, **kwargs)
            if threading.current_thread().name == "yoke-native-owner-reap":
                reaped.set()
            return result

        process.wait = observed_wait
        return process

    started = spawn_supervised_native(
        [sys.executable, "-c", "import sys; print('current refusal', file=sys.stderr); sys.exit(7)"],
        checkout=tmp_path,
        environment={},
        attempt_id="11111111-1111-4111-8111-111111111111",
        native_session_id="22222222-2222-4222-8222-222222222222",
        binary_source="path",
        supervision_kind="launch",
        state_dir=tmp_path,
        process_factory=factory,
    )
    assert started is not None
    refusal = immediate_native_refusal(started.capture_path)
    assert refusal is not None
    assert refusal.exit_code == 7
    assert b"current refusal" in refusal.stderr
    assert reaped.wait(timeout=10), "the owner reaper must wait for this supervisor"
    assert processes[0].returncode == 0


@pytest.mark.parametrize("token", [b"", b"invalid\n", supervisor.CUSTODY_READY])
def test_supervisor_starts_native_only_after_custody_token(tmp_path, monkeypatch, token):
    started = []
    monkeypatch.setattr(supervisor.sys, "stdin", SimpleNamespace(buffer=BytesIO(token)))
    monkeypatch.setattr(supervisor, "supervise", lambda *args: started.append(args) or 7)
    capture = tmp_path / "capture"
    result = supervisor.main(["--capture", str(capture), "--await-custody", "--", "native"])
    if token == supervisor.CUSTODY_READY:
        assert result == 7
        assert started == [(capture, ["native"])]
    else:
        assert result == 1
        assert not started
