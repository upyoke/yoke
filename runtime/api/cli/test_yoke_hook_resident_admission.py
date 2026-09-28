"""Request admission and the connect budget hold up while telemetry fails.

Every session on a machine shares one resident, so anything the accept
loop waits on between requests is paid by every hook on the machine. The
same is true of the client's connect grace: a budget checked only at the
top of a retry loop is not a budget.
"""

from __future__ import annotations

import socket
import threading
import time
from unittest.mock import Mock

import pytest

from yoke_cli.hook_resident_client import (
    RESIDENT_CONNECT_GRACE_SECONDS,
    ResidentUnavailable,
    _connect_timeout_seconds,
    _result_timeout_seconds,
    evaluate_with_resident,
)
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
    monkeypatch,
) -> None:
    # Exercise the retry deadline without a scheduler-dependent socket server.
    monkeypatch.setattr(
        "yoke_cli.hook_resident_client._round_trip",
        lambda *_args, **_kwargs: {
            "status": "restart",
            "loaded_revision": "aaaaaaaaaaaa",
            "requested_revision": "bbbbbbbbbbbb",
        },
    )

    started = time.monotonic()
    with pytest.raises(ResidentUnavailable) as raised:
        evaluate_with_resident("PreToolUse", "{}")
    elapsed = time.monotonic() - started
    assert elapsed < RESIDENT_CONNECT_GRACE_SECONDS + 0.5, f"waited {elapsed:.2f}s"
    assert raised.value.code == "YOKE_HOOK_RESIDENT_UNREACHABLE"
    # Both revisions are named, so a stuck upgrade reads from one line.
    assert "aaaaaaaaaaaa" in raised.value.detail
    assert "bbbbbbbbbbbb" in raised.value.detail
    assert raised.value.resident_wait_ms > 0
