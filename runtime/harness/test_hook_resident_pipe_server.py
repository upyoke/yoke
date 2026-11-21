"""The Windows resident keeps accepting after one failed pipe accept.

A client that abandons the pipe mid-connect surfaces as an ``OSError`` from
``Listener.accept``; CPython's ``PipeListener.accept`` can also end in
``assert err == 0``. Either one alone must leave the server answering the
next request. Only a listener that keeps failing ends the resident, after a
bounded number of paced retries.
"""

from __future__ import annotations

import socketserver
import threading
import time
from multiprocessing import connection
from unittest.mock import Mock

import pytest

from yoke_contracts import hook_resident_pipe_server as pipe_server

pytestmark = pytest.mark.windows


class _ScriptedListener:
    """Raise or return each scripted outcome, then block until closed."""

    def __init__(self, outcomes, *, repeat_last=False):
        self.outcomes = list(outcomes)
        self.repeat_last = repeat_last
        self.calls = 0
        self.closed = threading.Event()

    def accept(self):
        self.calls += 1
        if not self.outcomes:
            self.closed.wait()
            raise OSError("listener closed")
        outcome = self.outcomes[0] if self.repeat_last and len(
            self.outcomes
        ) == 1 else self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        self.closed.set()


def _server(monkeypatch, listener, answered):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            answered.append(self.request)

    monkeypatch.setattr(connection, "Listener", lambda *a, **k: listener)
    server = pipe_server.PipeServer("pipe", Handler)
    server.timeout = 2.0
    return server


@pytest.mark.parametrize(
    "failure",
    [OSError(232, "The pipe is being closed"), AssertionError()],
    ids=["oserror", "assertion"],
)
def test_one_failed_accept_leaves_the_server_answering(monkeypatch, failure):
    client = Mock()
    listener = _ScriptedListener([failure, client])
    answered = []
    server = _server(monkeypatch, listener, answered)
    try:
        server.handle_request()
        for _ in range(200):
            if answered:
                break
            time.sleep(0.01)
        assert [peer.peer for peer in answered] == [client]
        client.close.assert_called_once()
    finally:
        server.server_close()


def test_a_listener_that_always_fails_ends_the_resident_without_spinning(
    monkeypatch,
):
    listener = _ScriptedListener([OSError(5, "denied")], repeat_last=True)
    server = _server(monkeypatch, listener, [])
    started = time.monotonic()
    try:
        with pytest.raises(OSError, match="denied"):
            server.handle_request()
        elapsed = time.monotonic() - started
    finally:
        server.server_close()
    assert listener.calls == pipe_server.MAX_ACCEPT_FAILURES
    retries = pipe_server.MAX_ACCEPT_FAILURES - 1
    assert elapsed >= retries * pipe_server.ACCEPT_RETRY_SECONDS * 0.9


def test_a_success_resets_the_failure_count(monkeypatch):
    limit = pipe_server.MAX_ACCEPT_FAILURES
    first, second = Mock(), Mock()
    outcomes = [OSError("x")] * (limit - 1) + [first]
    outcomes += [OSError("y")] * (limit - 1) + [second]
    listener = _ScriptedListener(outcomes)
    answered = []
    server = _server(monkeypatch, listener, answered)
    try:
        server.handle_request()
        server.handle_request()
        for _ in range(200):
            if len(answered) == 2:
                break
            time.sleep(0.01)
        assert [peer.peer for peer in answered] == [first, second]
    finally:
        server.server_close()
