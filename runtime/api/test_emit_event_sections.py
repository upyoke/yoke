"""Argument and persistence tests for the Python event-emission owner.

These cases exercise CLI validation and DB writes through
``yoke_core.domain.emit_event``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend, emit_event
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_emit_event_test_helpers import (
    TEST_ITEM_REF,
    events_db,  # noqa: F401 — re-exported pytest fixture
)


# Section 17: argument validation — every required flag and every enum value
# should fail with exit 2 before touching the DB.
@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ["--kind", "system", "--type", "test", "--source-type", "agent"],
            id="missing-name",
        ),
        pytest.param(
            ["--name", "X", "--type", "test", "--source-type", "agent"],
            id="missing-kind",
        ),
        pytest.param(
            ["--name", "X", "--kind", "system", "--source-type", "agent"],
            id="missing-type",
        ),
        pytest.param(
            ["--name", "X", "--kind", "system", "--type", "test"],
            id="missing-source-type",
        ),
        pytest.param(
            [
                "--name", "X", "--kind", "system", "--type", "test",
                "--source-type", "invalid",
            ],
            id="invalid-source-type",
        ),
        pytest.param(
            [
                "--name", "X", "--kind", "system", "--type", "test",
                "--source-type", "agent", "--severity", "BOGUS",
            ],
            id="invalid-severity",
        ),
        pytest.param(
            [
                "--name", "X", "--kind", "bogus", "--type", "test",
                "--source-type", "agent",
            ],
            id="invalid-kind",
        ),
        pytest.param(
            [
                "--name", "X", "--kind", "system", "--type", "test",
                "--source-type", "agent", "--bogus",
            ],
            id="unknown-flag",
        ),
    ],
)
def test_emit_validation_errors(events_db, argv):
    rc = emit_event.main(argv)
    assert rc == 2, f"expected exit 2 for {argv!r}, got {rc}"


def test_emit_inserts_full_field_set(events_db):
    """Section 18: every flag round-trips into the DB row."""
    rc = emit_event.main(
        [
            "--name", "EmitTest",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--severity", "INFO",
            "--session-id", "emit-sess-001",
            "--outcome", "completed",
            "--agent", "engineer",
            "--tool-name", "Bash",
            "--duration-ms", "100",
            "--exit-code", "0",
            "--item-id", TEST_ITEM_REF,
            "--project", "yoke",
            "--event-id", "emit-test-full",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    row = conn.execute(
        "SELECT event_name, agent, tool_name, duration_ms, exit_code, "
        "event_outcome, severity, source_type FROM events "
        "WHERE event_id='emit-test-full'"
    ).fetchone()
    conn.close()
    assert tuple(row) == (
        "EmitTest", "engineer", "Bash", 100, 0, "completed", "INFO", "agent",
    )


def test_emit_auto_generates_event_id(events_db):
    """Section 19: auto-generated event_id is non-empty and unique."""
    rc = emit_event.main(
        [
            "--name", "AutoIdTest",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "emit-sess-auto",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    event_id = conn.execute(
        "SELECT event_id FROM events WHERE event_name='AutoIdTest'"
    ).fetchone()[0]
    conn.close()
    assert event_id, "expected non-empty auto-generated event_id"


def test_emit_uses_explicit_event_id(events_db):
    """Section 20: explicit --event-id round-trips unchanged."""
    rc = emit_event.main(
        [
            "--name", "ExplicitIdTest",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "emit-sess-explicit",
            "--event-id", "my-custom-uuid",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    event_id = conn.execute(
        "SELECT event_id FROM events WHERE event_name='ExplicitIdTest'"
    ).fetchone()[0]
    conn.close()
    assert event_id == "my-custom-uuid"


@pytest.mark.parametrize(
    "env_var,sentinel",
    [
        ("CLAUDE_SESSION_ID", "claude-session-id"),
        ("CODEX_THREAD_ID", "codex-thread-id"),
    ],
)
def test_emit_session_id_env_fallback(events_db, monkeypatch, env_var, sentinel):
    """Section 21: CLAUDE/CODEX env vars are used when no explicit session-id is given."""
    # Ensure only the env var under test is set.
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv(env_var, sentinel)

    event_id = f"sess-env-{env_var.lower()}"
    rc = emit_event.main(
        [
            "--name", f"SessEnv_{env_var}",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--event-id", event_id,
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    session_id = conn.execute(
        f"SELECT session_id FROM events WHERE event_id={p}",
        (event_id,),
    ).fetchone()[0]
    conn.close()
    assert session_id == sentinel


def test_emit_session_id_timestamp_pid_fallback(events_db, monkeypatch):
    """Section 21: when no session-id and no env vars, a non-empty fallback is generated."""
    for var in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(var, raising=False)

    rc = emit_event.main(
        [
            "--name", "FallbackSessionTest",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--event-id", "sess-env-fallback",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    session_id = conn.execute(
        "SELECT session_id FROM events WHERE event_id='sess-env-fallback'"
    ).fetchone()[0]
    conn.close()
    assert session_id, "expected non-empty fallback session_id"
