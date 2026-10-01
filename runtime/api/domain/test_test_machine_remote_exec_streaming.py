"""Remote exec streams both pipes while retaining bounded diagnostic tails."""

from __future__ import annotations

import subprocess
import sys
import threading
import tracemalloc

import pytest

from yoke_harness.test_machine_remote_exec import (
    DIAGNOSTIC_TAIL_BYTES,
    RemoteExecRefusal,
    run_remote_command,
)
from yoke_harness.ssh_mac_gui_session import classify_macos_session_context_failure


def _execute(tmp_path, program):
    def popen(argv, **kwargs):
        return subprocess.Popen([sys.executable, "-c", program], **kwargs)

    return run_remote_command(
        host="test.example",
        user="tester",
        command=["command"],
        yoke_home=tmp_path,
        environ={"SSH_AUTH_SOCK": "/tmp/agent.sock"},
        popen=popen,
    )


def test_both_streams_arrive_before_child_exits_without_a_newline(
    tmp_path, monkeypatch
):
    release = tmp_path / "release"
    arrived = [threading.Event(), threading.Event()]
    output = [[], []]

    class Sink:
        def __init__(self, index):
            self.index = index

        def write(self, text):
            output[self.index].append(text)

        def flush(self):
            if "ready" in "".join(output[self.index]):
                arrived[self.index].set()

    monkeypatch.setattr(sys, "stdout", Sink(0))
    monkeypatch.setattr(sys, "stderr", Sink(1))
    program = (
        "import sys, time; from pathlib import Path; "
        "sys.stdout.write('ready'); sys.stdout.flush(); "
        "sys.stderr.write('ready'); sys.stderr.flush(); "
        f"release = Path({str(release)!r}); deadline = time.monotonic() + 5\n"
        "while not release.exists() and time.monotonic() < deadline: time.sleep(.01)\n"
        "sys.exit(0 if release.exists() else 9)"
    )
    results = []
    worker = threading.Thread(
        target=lambda: results.append(_execute(tmp_path, program))
    )
    worker.start()
    try:
        assert all(event.wait(2) for event in arrived)
        assert worker.is_alive()
    finally:
        release.touch()
        worker.join(6)
    assert not worker.is_alive()
    assert results[0].returncode == 0
    assert ["".join(parts) for parts in output] == ["ready", "ready"]


def test_large_output_keeps_only_each_tail_and_bounded_memory(tmp_path, monkeypatch):
    class Sink:
        def __init__(self):
            self.count = 0

        def write(self, text):
            self.count += len(text)

        def flush(self):
            pass

    stdout, stderr = Sink(), Sink()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    amount = 8 * 1024 * 1024
    program = (
        "import os\n"
        f"for _ in range({amount // 4096}):\n"
        " os.write(1, b'o' * 4096); os.write(2, b'e' * 4096)\n"
        "os.write(1, b'OUT'); os.write(2, b'ERR')"
    )
    tracemalloc.start()
    try:
        result = _execute(tmp_path, program)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert stdout.count == stderr.count == amount + 3
    assert result.stdout == "o" * (DIAGNOSTIC_TAIL_BYTES - 3) + "OUT"
    assert result.stderr == "e" * (DIAGNOSTIC_TAIL_BYTES - 3) + "ERR"
    assert peak < 2 * 1024 * 1024


@pytest.mark.parametrize("stream", [1, 2])
@pytest.mark.parametrize(
    "signature",
    [
        "Your macOS login keychain is locked",
        "Not logged in · Please run /login",
    ],
)
def test_failure_tail_preserves_keychain_diagnosis(tmp_path, capsys, stream, signature):
    program = (
        "import os, sys; "
        f"os.write({stream}, b'x' * {DIAGNOSTIC_TAIL_BYTES * 2}); "
        f"os.write({stream}, {signature.encode()!r}); sys.exit(7)"
    )
    result = _execute(tmp_path, program)
    failure = classify_macos_session_context_failure(result, ssh_exec=True)
    assert result.returncode == 7
    assert failure.error_code == "macos_login_keychain_context_unavailable"
    captured = capsys.readouterr()
    assert getattr(captured, "out" if stream == 1 else "err").endswith(signature)


def test_missing_ssh_client_keeps_named_refusal_and_recovery(tmp_path):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("ssh")

    with pytest.raises(RemoteExecRefusal) as refusal:
        run_remote_command(
            host="test.example",
            user="tester",
            command=["command"],
            yoke_home=tmp_path,
            environ={"SSH_AUTH_SOCK": "/tmp/agent.sock"},
            popen=unavailable,
        )
    assert refusal.value.code == "test_machine_ssh_unavailable"
    assert refusal.value.recovery == (
        "Install OpenSSH's `ssh` client on this machine and put it on PATH."
    )
