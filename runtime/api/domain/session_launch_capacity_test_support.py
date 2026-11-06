# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from functools import partial

from dataclasses import replace

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

from yoke_core.domain.session_launch_capacity import (
    MACHINE_AT_CAPACITY,
    live_lane_count,
    machine_capacity,
)

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility

from yoke_core.domain.session_launch_requests import create_launch

from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
)

from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    level_connection,
)

launch_connection = partial(level_connection, CODEX_SOL)

_worker_launch = partial(
    assigned_launch, work_required=True, model="gpt-6.1-sol", reasoning_effort="medium"
)

MACHINE = "machine-1"


def _publish_capacity(conn, *, max_worker_lanes: int | None, relay_id="relay-1"):
    document = {
        "total_memory_bytes": 48 * 1024**3,
        "free_memory_bytes": 44 * 1024**2,
        "load_average_1m": 31.2,
        "core_count": 18,
        "max_worker_lanes": max_worker_lanes,
        "cap_source": "derived_from_total_memory",
        "observed_at": NOW,
    }
    conn.execute(
        "UPDATE session_relays SET machine_capacity=? WHERE relay_id=?",
        (json.dumps(document), relay_id),
    )
    conn.commit()


def _live_session(
    conn, session_id: str, *, machine_id: str = MACHINE, model="gpt-6.1-sol"
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id, executor_surface, "
        "executor_version, machine_id, model) VALUES (?, 10, 'codex-cli', "
        "'0.148.0a15', ?, ?)",
        (session_id, machine_id, model),
    )
    launch = _worker_launch(conn, key=session_id, machine_id=machine_id, model=model)
    conn.execute(
        "UPDATE session_launches SET registered_session_id=? WHERE launch_id=?",
        (session_id, launch.launch_id),
    )
    conn.commit()


def _eligibility(conn):
    return derive_launch_eligibility(
        conn,
        project_id=10,
        surface="codex-cli",
        machine_id=None,
        now=parse_instant(NOW),
    )
