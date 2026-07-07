"""Envelope/category coverage for the Python event-emission owner.

These cases exercise CLI-level envelope persistence, source categories,
and event metadata through ``yoke_core.domain.emit_event``.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import emit_event
from yoke_core.domain.events import emit_event as emit_event_direct
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_emit_event_test_helpers import (
    events_db,  # noqa: F401 — re-exported pytest fixture
)


def test_emit_envelope_is_valid_json_with_key_fields(events_db):
    """Section 23: the stored envelope is valid JSON and contains event identifiers."""
    rc = emit_event.main(
        [
            "--name", "EnvelopeTest",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "env-sess",
            "--event-id", "env-eid-001",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    envelope = conn.execute(
        "SELECT envelope FROM events WHERE event_id='env-eid-001'"
    ).fetchone()[0]
    conn.close()
    parsed = json.loads(envelope)  # must not raise
    assert parsed["event_name"] == "EnvelopeTest"
    assert parsed["event_id"] == "env-eid-001"


@pytest.mark.parametrize(
    "category",
    [
        "agent_failure",
        "hook_failure",
        "db",
        "git",
        "dispatch",
        "validation",
        "external",
        "unknown",
    ],
)
def test_emit_valid_error_categories_accepted(events_db, category):
    """Section 25: every documented error_category value is accepted."""
    rc = emit_event.main(
        [
            "--name", f"GoodCat_{category}",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "cat-sess",
            "--event-id", f"cat-{category}",
            "--error-context", json.dumps({"error_category": category}),
        ]
    )
    assert rc == 0, f"error_category {category!r} should be accepted"


@pytest.mark.parametrize(
    "kind",
    ["analytics", "system", "audit", "security", "metric"],
)
def test_emit_all_event_kinds_accepted(events_db, kind):
    """Section 26: every documented event_kind value is accepted."""
    rc = emit_event.main(
        [
            "--name", f"Kind_{kind}",
            "--kind", kind,
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "kind-sess",
            "--event-id", f"kind-{kind}",
        ]
    )
    assert rc == 0, f"kind {kind!r} should be accepted"


def test_emit_escapes_single_quote_in_event_name(events_db):
    """Section 27: single-quote in event_name is stored verbatim (no SQL injection)."""
    rc = emit_event.main(
        [
            "--name", "O'Reilly",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "sess-escape",
            "--event-id", "evt-escape",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    stored = conn.execute(
        "SELECT event_name FROM events WHERE event_id='evt-escape'"
    ).fetchone()[0]
    conn.close()
    assert stored == "O'Reilly"


def test_emit_default_values_match_documented_contract(events_db):
    """Section 29: default severity=INFO, service=cli, project=yoke."""
    rc = emit_event.main(
        [
            "--name", "DefaultsTest",
            "--kind", "system",
            "--type", "test",
            "--source-type", "agent",
            "--session-id", "defaults-sess",
            "--event-id", "evt-defaults",
        ]
    )
    assert rc == 0

    conn = connect_test_db(events_db)
    severity, service, project = conn.execute(
        "SELECT e.severity, e.service, p.slug "
        "FROM events e JOIN projects p ON p.id = e.project_id "
        "WHERE event_id='evt-defaults'"
    ).fetchone()
    conn.close()
    assert severity == "INFO"
    assert service == "cli"
    assert project == "yoke"


@pytest.mark.parametrize("event_type", ["session_lifecycle", "hook_dispatch"])
def test_session_scoped_event_project_follows_session(events_db, event_type):
    conn = connect_test_db(events_db)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            actor_id INTEGER,
            project_id INTEGER NOT NULL REFERENCES projects(id)
        )
        """
    )
    conn.execute(
        f"INSERT INTO harness_sessions (session_id, actor_id, project_id) "
        f"VALUES ({p}, {p}, {p})",
        ("sess-buzz", None, 2),
    )
    conn.commit()

    result = emit_event_direct(
        f"SessionProject_{event_type}",
        event_kind="system",
        event_type=event_type,
        source_type="hook",
        session_id="sess-buzz",
        severity="INFO",
        outcome="completed",
        project="yoke",
        conn=conn,
    )

    assert result.ok
    project = conn.execute(
        "SELECT p.slug "
        "FROM events e JOIN projects p ON p.id = e.project_id "
        f"WHERE e.event_id = {p}",
        (result.event_id,),
    ).fetchone()[0]
    conn.close()
    assert project == "buzz"


@pytest.mark.parametrize(
    "source_type",
    ["script", "hook", "skill", "agent", "backend", "frontend", "system"],
)
def test_emit_accepts_all_source_types(events_db, source_type):
    """Section 31: extended source_type values are all accepted."""
    rc = emit_event.main(
        [
            "--name", f"SourceType_{source_type}",
            "--kind", "system",
            "--type", "test",
            "--source-type", source_type,
            "--session-id", "sess-867",
            "--event-id", f"evt-867-{source_type}",
        ]
    )
    assert rc == 0, f"source_type {source_type!r} should be accepted"

    conn = connect_test_db(events_db)
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    stored = conn.execute(
        f"SELECT source_type FROM events WHERE event_id={p}",
        (f"evt-867-{source_type}",),
    ).fetchone()[0]
    conn.close()
    assert stored == source_type
