"""Request admission holds up while telemetry fails.

Every session on a machine shares one resident, so anything the accept
loop waits on between requests is paid by every hook on the machine.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import Mock

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

