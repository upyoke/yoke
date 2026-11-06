# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.machine_registry import register_machine

from yoke_core.domain.overview_machine_activation import (
    MACHINE_MODULE_CONNECT_HARNESS,
    MACHINE_MODULE_MACHINE_CONNECTED,
    every_machine_has_harness,
    latch_machine_activations,
    machine_module_rows,
    read_registered_machines,
)

MACHINE_A = "11111111-1111-4111-8111-111111111111"


def _seed_relay(
    conn,
    machine_id,
    hostname,
    *,
    state="active",
    surfaces=None,
    seen="2026-08-01T00:00:00Z",
    actor_id=None,
):
    actor = (
        actor_id
        if actor_id is not None
        else conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    register_machine(
        conn, machine_id=machine_id, name=hostname, actor_id=actor, now=seen
    )
    conn.execute(
        "INSERT INTO session_relays (relay_id, actor_id, machine_id, hostname, "
        "surface_versions, project_checkouts, first_seen_at, last_seen_at, "
        "connected_until, state) VALUES (%s, %s, %s, %s, %s, '[]', %s, %s, %s, %s)",
        (
            f"machine:{machine_id}",
            actor,
            machine_id,
            hostname,
            surfaces or '{"claude-cli": "2.1"}',
            seen,
            seen,
            seen,
            state,
        ),
    )
    conn.commit()


def _seed_session(
    conn,
    session_id,
    machine_id,
    *,
    executor="claude-code",
    surface="claude-cli",
    at=None,
    tool_calls=0,
    actor_id=None,
):
    at = at or iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, executor_surface, "
        "machine_id, provider, model, workspace, project_id, mode, offered_at, "
        "last_heartbeat, tool_call_count, actor_id) "
        "VALUES (%s, %s, %s, %s, 'anthropic', 'm', '/w', 1, 'wait', %s, %s, %s, %s)",
        (session_id, executor, surface, machine_id, at, at, tool_calls, actor_id),
    )
    conn.commit()
