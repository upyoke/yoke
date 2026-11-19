"""The in-container handoff client prints one closed failure class on stdout."""

import io
import json
import shutil
import socket
import sys
import tempfile
import threading
import types

import pytest

from yoke_contracts.machine_config.directories import shortest_temp_directory
from yoke_core.tools import self_host_handoff
from yoke_contracts.self_host_bootstrap_output import TOKEN_PREFIX, TOKEN_BODY_LENGTH

TOKEN = TOKEN_PREFIX + "C" * TOKEN_BODY_LENGTH
POSIX = pytest.mark.posix_only(reason="the handoff socket is a Unix socket")


@pytest.fixture
def handoff(monkeypatch):
    """A short-lived socket path, a short deadline and a scripted stdin."""
    directory = tempfile.mkdtemp(dir=shortest_temp_directory())
    path = f"{directory}/handoff.sock"
    monkeypatch.setattr(self_host_handoff, "HANDOFF_SOCKET", path)
    monkeypatch.setattr(self_host_handoff, "HANDOFF_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(self_host_handoff, "_health_status", lambda: None)
    monkeypatch.setattr(sys, "argv", ["self_host_handoff"])

    def stdin(data: bytes):
        monkeypatch.setattr(
            sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(data))
        )

    yield types.SimpleNamespace(path=path, stdin=stdin)
    shutil.rmtree(directory, ignore_errors=True)


def _bootstrap(path, behave):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)

    def serve():
        connection, _ = listener.accept()
        with connection:
            connection.recv(4096)
            behave(connection)
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def _run(capsys):
    code = self_host_handoff.main()
    captured = capsys.readouterr()
    return code, captured.out.splitlines(), captured.err


@POSIX
def test_missing_socket_reports_connect_timeout(handoff, capsys):
    handoff.stdin(b"{}\n")
    code, out, _ = _run(capsys)
    assert code == 1
    assert out == ['{"error":"connect_timeout"}']


@POSIX
def test_closed_bootstrap_reports_bootstrap_closed(handoff, capsys):
    handoff.stdin(b"{}\n")
    _bootstrap(handoff.path, lambda connection: None)
    code, out, _ = _run(capsys)
    assert code == 1
    assert out == ['{"error":"bootstrap_closed"}']


@POSIX
def test_unacknowledged_token_reports_ack_missing(handoff, capsys):
    handoff.stdin(b"{}\n")
    gate = threading.Event()

    def deliver(connection):
        connection.sendall(TOKEN.encode() + b"\n")
        gate.wait(2)

    _bootstrap(handoff.path, deliver)
    code, out, _ = _run(capsys)
    gate.set()
    assert code == 1
    assert json.loads(out[0]) == {"token": TOKEN}
    assert out[1:] == ['{"error":"ack_missing"}']


@POSIX
def test_silent_bootstrap_reports_unhealthy_timeout(handoff, capsys):
    handoff.stdin(b"{}\n")
    gate = threading.Event()
    _bootstrap(handoff.path, lambda connection: gate.wait(2))
    code, out, _ = _run(capsys)
    gate.set()
    assert code == 1
    assert out == ['{"error":"unhealthy_timeout"}']


@POSIX
def test_unclassified_failure_names_only_its_class_on_stderr(handoff, capsys):
    handoff.stdin(b"no newline " + TOKEN.encode())
    code, out, err = _run(capsys)
    assert code == 1
    assert out == []
    assert err.startswith("self_host_handoff_client_failed: ValueError;")
    assert TOKEN not in err


def test_failure_classes_are_closed():
    with pytest.raises(ValueError, match="unknown handoff failure class"):
        self_host_handoff._HandoffFailure("novel")
