"""Level placement counts live workers per machine and surface, in flight too."""

from __future__ import annotations

import json

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    NOW,
    PROJECT_ID,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.session_launch_level_pools import live_workers


def _launch(conn, launch_id: str, *, state: str, machine: str, registered=None):
    message_id = f"msg-{launch_id}"
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'launch instruction', 'sha', %s, %s, %s)",
        (message_id, ACTOR_ID, "steering-holder", json.dumps({}), NOW, NOW),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, allow_surface_fallback, message_id, state, "
        "deadline_at, created_at, origin, assigned_machine_id, "
        "registered_session_id) "
        "VALUES (%s, %s, %s, 'claude-cli', 'claude-cli', 0, %s, %s, %s, %s, "
        "'steering', %s, %s)",
        (
            launch_id,
            ACTOR_ID,
            PROJECT_ID,
            message_id,
            state,
            NOW,
            NOW,
            machine,
            registered,
        ),
    )


def test_live_sessions_and_unregistered_launches_both_count(test_db) -> None:
    conn = seed_steering_scope(test_db)
    # seed_steering_scope leaves two live codex-cli sessions on machine-1.
    seed_session(conn, "claude-worker", executor_surface="claude-cli")
    seed_session(conn, "ended-worker", executor_surface="claude-cli", ended_at=NOW)
    seed_session(
        conn, "terminated-worker", executor_surface="claude-cli", terminated_at=NOW
    )
    _launch(conn, "in-flight", state="awaiting_registration", machine="machine-2")
    _launch(conn, "queued", state="assigned", machine="machine-2")
    _launch(
        conn,
        "registered",
        state="awaiting_registration",
        machine="machine-2",
        registered="claude-worker",
    )
    _launch(conn, "failed", state="failed", machine="machine-2")
    conn.commit()

    counts = live_workers(conn)

    assert counts[("machine-1", "codex-cli")] == 2
    assert counts[("machine-1", "claude-cli")] == 1
    assert counts[("machine-2", "claude-cli")] == 2
