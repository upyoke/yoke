"""Byte streams preserve partial lines, deadlines, EOF and reader errors."""

import subprocess
import sys

import pytest

from yoke_contracts.byte_stream_reader import ByteStreamReader
from yoke_harness import ssh_test_machine_transport as transport


def test_timed_read_then_drain_after_child_stop():
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,time; os.write(1,b'partial'); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with process, ByteStreamReader((process.stdout, process.stderr)) as reader:
        try:
            assert reader.read(timeout=10) == (process.stdout, b"partial")
            assert reader.read(timeout=0.01) is None
        finally:
            process.kill()
            process.wait()
        events = []
        while reader.pending:
            event = reader.read(timeout=10)
            assert event is not None
            events.append(event)
        assert set(events) == {(process.stdout, b""), (process.stderr, b"")}


def test_reader_exception_reaches_consumer():
    class BrokenStream:
        def fileno(self):
            raise OSError("pipe read failed")

    with ByteStreamReader((BrokenStream(),)) as reader:
        with pytest.raises(OSError, match="pipe read failed"):
            reader.read(timeout=10)


def test_windows_client_never_adds_unix_control_options(tmp_path, monkeypatch):
    monkeypatch.setattr(transport.sys, "platform", "win32")
    monkeypatch.setattr(
        transport.SshTestMachineTransport,
        "_host_facts",
        lambda self: {
            "home": "/home/tester",
            "shell": "/bin/bash",
        },
        raising=False,
    )
    machine = transport.SshTestMachineTransport(
        settings={"os": "linux", "host": "host", "user": "tester"},
        key_path=tmp_path / "key",
    )
    assert not any(part.startswith("Control") for part in machine._ssh_argv("true"))
    assert machine.path_state.home == "/home/tester"
    assert machine.path_state.shell == "bash"
    assert machine.path_state.yoke_bin == "/home/tester/.local/bin/yoke"
