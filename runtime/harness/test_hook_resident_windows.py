"""Named-pipe wire, budget and native Windows evaluator coverage."""

import os
import socket
import threading
import time
from types import SimpleNamespace
from multiprocessing import Pipe, connection
from unittest.mock import Mock

import pytest

from yoke_contracts import hook_resident_transport as transport
from yoke_contracts.hook_evaluator_protocol import receive_frame, send_frame

pytestmark = pytest.mark.windows


def test_pipe_peer_keeps_json_framing_and_bounds_reads():
    left, right = Pipe()
    a, b = transport.PipePeer(left), transport.PipePeer(right)
    try:
        a.settimeout(0.05)
        b.settimeout(0.05)
        send_frame(a, {"kind": "health", "unicode": "雪"})
        assert receive_frame(b) == {"kind": "health", "unicode": "雪"}
        with pytest.raises(socket.timeout):
            b.recv(4)
    finally:
        a.close()
        b.close()


def test_pipe_connect_deadline_closes_a_late_connection(monkeypatch):
    release = threading.Event()
    peer = Mock()

    def connect(*args, **kwargs):
        release.wait(1)
        return peer

    monkeypatch.setattr(connection, "Client", connect)
    with pytest.raises(socket.timeout):
        transport.connect_pipe("pipe", time.monotonic() + 0.01)
    release.set()
    for _ in range(100):
        if peer.close.called:
            break
        time.sleep(0.005)
    peer.close.assert_called_once()


def test_blocked_pipe_write_obeys_timeout():
    release = threading.Event()
    peer = Mock()
    peer.send_bytes.side_effect = lambda data: release.wait(1)
    wrapped = transport.PipePeer(peer)
    wrapped.settimeout(0.01)
    try:
        with pytest.raises(socket.timeout):
            wrapped.sendall(b"frame")
        peer.close.assert_called_once()
    finally:
        release.set()


def test_windows_pipe_path_is_stable_and_not_a_filesystem_socket(monkeypatch, tmp_path):
    from yoke_cli import hook_resident_paths as paths

    monkeypatch.setattr(paths.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "uses_named_pipe", lambda: True)
    first = paths.resident_paths()
    assert str(first.socket).startswith("\\\\.\\pipe\\yoke-hook-")
    assert first == paths.resident_paths()
    assert paths.resident_transport_available()
    assert paths.resident_transport_refusal(first) is None


@pytest.mark.parametrize(
    "executable",
    [
        "/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python",
        "/venv/bin/python3",
        r"C:\Python\python.exe",
    ],
)
def test_discovered_python_resident_stops_and_releases_startup_lock(
    monkeypatch, tmp_path, executable
):
    import yoke_contracts
    from yoke_cli import hook_resident_client as client
    from yoke_cli import hook_resident_lifecycle as lifecycle
    from yoke_cli import hook_resident_start as startup

    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    paths = client.resident_paths()
    held = [startup._open_start_lock(paths.lock)]
    assert held[0] is not None
    process = SimpleNamespace(
        pid=123,
        start_time=10.0,
        name="Python",
        cmdline=(
            executable,
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            str(paths.socket),
            "--lock-fd",
            str(held[0]),
        ),
    )
    handle = object()

    def rebuild(pid, started):
        assert (pid, started) == (process.pid, process.start_time)
        return handle

    def stop(custody, timeout):
        assert custody is handle and timeout == lifecycle._STOP_SECONDS
        os.close(held.pop())
        return True

    platform = SimpleNamespace(
        process_command_lines=lambda: [process],
        handle_from_pid=rebuild,
        stop_group=stop,
        pid_alive=lambda *args: bool(held),
    )
    monkeypatch.setattr(yoke_contracts, "platform_process", platform, raising=False)
    try:
        assert lifecycle._resident_processes(paths) == [
            (process.pid, process.start_time)
        ]
        lifecycle.stop_resident(paths)
        assert not held
        released = startup._open_start_lock(paths.lock)
        assert released is not None
        os.close(released)
    finally:
        if held:
            os.close(held.pop())


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows named pipes")
def test_windows_resident_warms_answers_health_and_stops(monkeypatch, tmp_path):
    from yoke_cli import hook_resident_client as client
    from yoke_cli import hook_resident_lifecycle as lifecycle
    from yoke_cli.hook_resident_health import resident_revision_problem
    from yoke_contracts.execution_provenance import collect_execution_provenance
    from yoke_contracts import platform_process

    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    paths = client.resident_paths()
    try:
        lifecycle.restart_resident()
        first = lifecycle._resident_processes(paths)
        # Windows virtualenv Python can retain a launcher beside its child.
        assert first
        assert (
            client.evaluate_with_resident("PreToolUse", "{}", dry_run=True).exit_code
            == 0
        )
        revision = collect_execution_provenance().get("source_sha")
        assert resident_revision_problem(paths.socket, revision) == ""
        lifecycle.restart_resident()
        second = lifecycle._resident_processes(paths)
        assert second
        assert set(second).isdisjoint(first)
        assert all(not platform_process.pid_alive(*identity) for identity in first)
        assert resident_revision_problem(paths.socket, revision) == ""
    finally:
        lifecycle.stop_resident()
    assert lifecycle._resident_processes(paths) == []


def test_windows_client_retries_start_after_retiring_resident_releases_lock(
    monkeypatch, tmp_path
):
    from yoke_cli import hook_resident_client as client

    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(client, "uses_named_pipe", lambda: True)
    peer = Mock()
    connect = Mock(
        side_effect=[ConnectionRefusedError(), ConnectionRefusedError(), peer]
    )
    launch = Mock(side_effect=[None, Mock()])
    monkeypatch.setattr(client, "_connect", connect)
    monkeypatch.setattr(client, "_start_resident", launch)
    monkeypatch.setattr(
        client,
        "_exchange",
        lambda *args: {"status": "ok", "stdout": "", "stderr": "", "exit_code": 0},
    )
    result = client.evaluate_with_resident("PreToolUse", "{}", dry_run=True)
    assert result.exit_code == 0
    assert launch.call_count == 2
    peer.close.assert_called_once()
