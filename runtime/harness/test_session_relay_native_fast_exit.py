"""Custody precedes execution, including natives that exit immediately."""

from io import BytesIO
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from yoke_contracts.owner_private_path import create_owner_private_directory
from yoke_harness import session_relay_native_supervisor as supervisor
from yoke_harness import session_launch_containment as containment
from yoke_harness.session_relay_native_create import immediate_native_refusal
from yoke_harness.session_relay_native_spawn import spawn_supervised_native
from yoke_harness.session_relay_process_group import spawn_relay_process

pytestmark = pytest.mark.windows


def test_current_native_exit_replaces_the_initialized_capture(tmp_path: Path, monkeypatch) -> None:
    tmp_path = create_owner_private_directory(tmp_path / "private-relay")
    reaped = threading.Event()
    processes = []
    stages = []
    errors = tmp_path / "supervisor.stderr"
    for name in ("process_start_time", "capture_process_tree", "write_record"):
        original = getattr(containment, name)

        def observed(*args, _name=name, _original=original, **kwargs):
            try:
                value = _original(*args, **kwargs)
            except Exception as exc:
                stages.append((_name, type(exc).__name__))
                raise
            stages.append((_name, bool(value)))
            return value

        monkeypatch.setattr(containment, name, observed)

    def factory(*args, **kwargs):
        with errors.open("wb") as error_stream:
            kwargs["stderr"] = error_stream
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
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read(); print('current refusal', file=sys.stderr); sys.exit(7)"],
        instruction=b"test instruction",
        checkout=tmp_path,
        # Windows asyncio needs SystemRoot to load Winsock: CPython issue #118234.
        environment={"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {},
        attempt_id="11111111-1111-4111-8111-111111111111",
        native_session_id="22222222-2222-4222-8222-222222222222",
        binary_source="path",
        supervision_kind="launch",
        state_dir=tmp_path,
        process_factory=factory,
    )
    assert started is not None, (
        f"supervisor exit={processes[0].returncode if processes else 'not spawned'}; "
        f"custody={stages}; stderr={errors.read_bytes()[-4096:] if errors.exists() else b''!r}"
    )
    # Read the settled capture after the supervisor publishes it and exits.
    assert reaped.wait(timeout=10), "the owner reaper must wait for this supervisor"
    assert processes[0].returncode == 0
    refusal = immediate_native_refusal(started.capture_path, window_seconds=0)
    assert refusal is not None
    assert refusal.exit_code == 7
    assert b"current refusal" in refusal.stderr


@pytest.mark.parametrize("token", [b"", b"invalid\n", supervisor.CUSTODY_READY + b"example"])
def test_supervisor_starts_native_only_after_custody_token(tmp_path, monkeypatch, token):
    started = []
    monkeypatch.setattr(supervisor.sys, "stdin", SimpleNamespace(buffer=BytesIO(token)))
    monkeypatch.setattr(supervisor, "supervise", lambda *args: started.append(args) or 7)
    capture = tmp_path / "capture"
    result = supervisor.main(["--capture", str(capture), "--await-custody", "--", "native"])
    if token.startswith(supervisor.CUSTODY_READY):
        assert result == 7
        assert started == [(capture, ["native"], b"example")]
    else:
        assert result == 1
        assert not started


def test_supervisor_delivers_instruction_bytes_after_custody(tmp_path, monkeypatch):
    tmp_path = create_owner_private_directory(tmp_path / "private-relay")
    instruction = b'Read "<x>" & | ^ %PATH%\nsecond line\r\nlast line'
    monkeypatch.setattr(
        supervisor.sys, "stdin", SimpleNamespace(buffer=BytesIO(supervisor.CUSTODY_READY + instruction))
    )
    capture = tmp_path / "capture"
    result = supervisor.main([
        "--capture", str(capture), "--await-custody", "--", sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
    ])

    assert result == 0
    settled = immediate_native_refusal(capture, window_seconds=0)
    assert settled is not None and settled.exit_code == 0
    assert settled.stdout == instruction


@pytest.mark.parametrize("instruction", [b"", b"x" * (supervisor.MAX_HANDOFF_BYTES + 1)])
def test_supervisor_refuses_invalid_instruction_before_native_spawn(tmp_path, monkeypatch, instruction):
    tmp_path = create_owner_private_directory(tmp_path / "private-relay")
    monkeypatch.setattr(
        supervisor.sys, "stdin", SimpleNamespace(buffer=BytesIO(supervisor.CUSTODY_READY + instruction))
    )

    def unexpected_spawn(*args, **kwargs):
        pytest.fail("native spawned")

    monkeypatch.setattr(supervisor.subprocess, "Popen", unexpected_spawn)
    capture = tmp_path / "capture"

    assert supervisor.main(["--capture", str(capture), "--await-custody", "--", "native"]) == 1
    settled = immediate_native_refusal(capture, window_seconds=0)
    assert settled is not None and settled.exit_code is None
    assert b"native_instruction_invalid" in settled.stderr


def test_supervisor_settles_failed_instruction_write(tmp_path, monkeypatch):
    tmp_path = create_owner_private_directory(tmp_path / "private-relay")

    class ClosedPipe(BytesIO):
        def write(self, data):
            raise BrokenPipeError("stdin closed")

    stopped = []
    process = SimpleNamespace(
        stdin=ClosedPipe(),
        stdout=None,
        stderr=None,
        kill=lambda: stopped.append("killed"),
        wait=lambda: stopped.append("reaped"),
    )
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(supervisor, "_install_stop_handler", lambda child: None)
    capture = tmp_path / "capture"

    assert supervisor.supervise(capture, ["native"], b"test instruction") == 1
    assert stopped == ["killed", "reaped"]
    settled = immediate_native_refusal(capture, window_seconds=0)
    assert settled is not None and settled.exit_code is None
    assert b"native_instruction_write_failed" in settled.stderr
