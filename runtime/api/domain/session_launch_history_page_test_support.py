# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.handlers import session_launch as handlers

from yoke_core.domain.session_launch_history_page import (
    OPERATIONAL_LAUNCH_STATES,
    read_launch_page,
)

from yoke_core.domain.session_launch_types import SessionLaunchError

from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)

import pytest


class _NoCloseConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass
