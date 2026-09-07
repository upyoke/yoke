"""Request admission and the connect budget hold up while telemetry fails.

Every session on a machine shares one resident, so anything the accept
loop waits on between requests is paid by every hook on the machine. The
same is true of the client's connect grace: a budget checked only at the
top of a retry loop is not a budget.
"""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from yoke_cli.hook_resident_client import (
    RESIDENT_CONNECT_GRACE_SECONDS,
    ResidentUnavailable,
    _connect_timeout_seconds,
    _result_timeout_seconds,
    evaluate_with_resident,
    resident_paths,
)
from yoke_contracts.hook_evaluator_protocol import receive_frame, send_frame
from yoke_harness.hook_resident import (
    RESTART_FOR_INSTALLED_REVISION,
    RETIRED_WHILE_IDLE,
    _exit_reason,
)


def _server(**attributes):
    from yoke_harness.hook_resident import _ResidentServer

    server = object.__new__(_ResidentServer)
    server.restart_event = threading.Event()
    server.observations = Mock()
    server.observations.pending_count.return_value = 0
    server.state_lock = threading.Lock()
    server.active_requests = 0
    server.last_activity = time.monotonic()
    for name, value in attributes.items():
        setattr(server, name, value)
    return server


def test_a_requested_revision_restarts_even_with_telemetry_retained() -> None:
    server = _server()
    server.observations.pending_count.return_value = 17
    server.restart_event.set()

    assert _exit_reason(server) == RESTART_FOR_INSTALLED_REVISION


def test_retained_telemetry_does_not_keep_an_idle_resident_alive() -> None:
    from yoke_contracts.hook_evaluator_protocol import RESIDENT_IDLE_TIMEOUT_SECONDS

    server = _server()
    server.observations.pending_count.return_value = 17
    server.last_activity = time.monotonic() - (RESIDENT_IDLE_TIMEOUT_SECONDS + 1)

    assert _exit_reason(server) == RETIRED_WHILE_IDLE


def test_a_busy_resident_keeps_serving() -> None:
    server = _server()
    server.active_requests = 1

    assert _exit_reason(server) is None


def test_connect_timeout_refuses_once_the_grace_is_spent() -> None:
    with pytest.raises(socket.timeout):
        _connect_timeout_seconds(time.monotonic() - 0.1)

    assert _connect_timeout_seconds(time.monotonic() + 10) <= 0.1


def test_the_response_wait_shrinks_by_what_the_connect_phase_spent() -> None:
    environment = {"YOKE_HOOK_TOTAL_TIMEOUT_MS": "10000"}
    ceiling = _result_timeout_seconds(environment, None)
    after_grace = _result_timeout_seconds(
        environment, time.monotonic() - RESIDENT_CONNECT_GRACE_SECONDS
    )

    assert ceiling == pytest.approx(12.0)
    assert after_grace == pytest.approx(10.0, abs=0.2)
    # However long was already spent, a real evaluation keeps a floor.
    assert _result_timeout_seconds(environment, time.monotonic() - 600) == 1.0


def test_a_resident_that_only_ever_restarts_gives_up_inside_the_grace(
    tmp_path, monkeypatch
) -> None:
    # AF_UNIX paths are short; pytest's tmp_path is not.
    socket_path = Path(tempfile.gettempdir()) / f"yoke-restart-{os.getpid()}.sock"
    socket_path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(16)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                listener.settimeout(0.2)
                peer, _ = listener.accept()
            except (OSError, socket.timeout):
                continue
            try:
                receive_frame(peer)
                send_frame(
                    peer,
                    {
                        "status": "restart",
                        "loaded_revision": "aaaaaaaaaaaa",
                        "requested_revision": "bbbbbbbbbbbb",
                    },
                )
            except (OSError, Exception):
                pass
            finally:
                peer.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    paths = resident_paths()
    monkeypatch.setattr(
        "yoke_cli.hook_resident_client.resident_paths",
        lambda: paths.__class__(
            state_dir=paths.state_dir,
            socket=socket_path,
            lock=tmp_path / "evaluator.lock",
            log=tmp_path / "evaluator.log",
        ),
    )
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    started = time.monotonic()
    with pytest.raises(ResidentUnavailable) as raised:
        evaluate_with_resident("PreToolUse", "{}")
    elapsed = time.monotonic() - started
    stop.set()
    thread.join(timeout=5)
    listener.close()
    socket_path.unlink(missing_ok=True)

    assert elapsed < RESIDENT_CONNECT_GRACE_SECONDS + 0.5, f"waited {elapsed:.2f}s"
    assert raised.value.code == "YOKE_HOOK_RESIDENT_UNREACHABLE"
    # Both revisions are named, so a stuck upgrade reads from one line.
    assert "aaaaaaaaaaaa" in raised.value.detail
    assert "bbbbbbbbbbbb" in raised.value.detail
    assert raised.value.resident_wait_ms > 0
