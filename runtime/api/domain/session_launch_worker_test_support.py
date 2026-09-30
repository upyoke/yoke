"""Fixtures for a launched worker that reached its mandate, or never did.

Both settlement paths — session end and verified native death — need one
delivered launch plus the activity tables the abandonment backstop reads,
so these sit beside the generic launch fixtures rather than inside either
test module.
"""

from __future__ import annotations

from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_for_message,
    complete_launch_injection,
    prepare_launch_registration,
)

from runtime.api.domain.session_launch_test_support import NOW, assigned_launch


#: The launched worker every abandonment fixture drives.
LAUNCH_WORKER_SESSION = "session-worker"


def add_worker_activity_tables(conn) -> None:
    """Add the work and activity state read by the abandonment backstop."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            released_at TEXT
        )"""
    )
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN last_tool_call_at TEXT")
    conn.execute(
        "ALTER TABLE harness_sessions ADD COLUMN tool_call_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    conn.commit()


def delivered_launch(conn, *, key: str = "mandate"):
    """Drive one launch all the way to succeeded, as a real worker does."""
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=LAUNCH_WORKER_SESSION,
        now="2026-08-22T12:00:30Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, "
        "machine_id, model) VALUES (?, 10, 'codex-cli', '0.148.0a15', "
        "'machine-1', 'gpt-5')",
        (LAUNCH_WORKER_SESSION,),
    )
    conn.commit()
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=LAUNCH_WORKER_SESSION,
        now="2026-08-22T12:00:31Z",
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected' "
        "WHERE message_id=? AND session_id=?",
        (launch.message_id, LAUNCH_WORKER_SESSION),
    )
    conn.commit()
    complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id=LAUNCH_WORKER_SESSION,
        injected=True,
        now="2026-08-22T12:00:32Z",
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged' WHERE message_id=?",
        (launch.message_id,),
    )
    conn.commit()
    return complete_launch_for_message(
        conn,
        message_id=launch.message_id,
        session_id=LAUNCH_WORKER_SESSION,
        now="2026-08-22T12:00:33Z",
    )

__all__ = [
    "LAUNCH_WORKER_SESSION",
    "add_worker_activity_tables",
    "delivered_launch",
]
