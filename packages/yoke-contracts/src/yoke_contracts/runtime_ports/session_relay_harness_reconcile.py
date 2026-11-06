"""Runtime interface for session relay harness reconcile."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class SessionRelayHarnessReconcile(Protocol):
    """Operations and values supplied by the executing adapter."""

    HarnessSetupResult: Any
    Path: Any
    RETRY_SECONDS: Any
    STATE_FILE: Any
    format_instant: Any
    installed_machine_hooks: Any
    json: Any
    os: Any
    read_reconcile_state: Callable[..., Any]
    reconcile_harness_setup: Any
    reconcile_on_change: Callable[..., Any]
    refresh_harness_inventory: Callable[..., Any]
    refresh_surface_probe_cache: Any
    relay_state_dir: Any
    remember_reconcile_result: Callable[..., Any]
    state_path: Callable[..., Any]
    tempfile: Any
    time: Any
    utc_now: Any


def get_session_relay_harness_reconcile() -> SessionRelayHarnessReconcile:
    return cast(SessionRelayHarnessReconcile, load_port("session_relay_harness_reconcile", SessionRelayHarnessReconcile))
