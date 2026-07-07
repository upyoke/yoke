"""Regression coverage for the path-claims shared events fixture."""

from __future__ import annotations

import json

from yoke_core.domain._path_claims_test_helpers import conn  # noqa: F401
from yoke_core.domain.path_claims_events import emit_registration_blocked


def _placeholder(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def test_path_claims_fixture_provisions_canonical_events_table(conn) -> None:
    event_id = emit_registration_blocked(
        conn=conn,
        item_id=1572,
        integration_target="main",
        reason="covered-by-test",
        project="yoke",
        session_id="sess-test",
    )

    assert event_id
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT event_name, severity, envelope FROM events WHERE event_id={p}",
        (event_id,),
    ).fetchone()
    assert row["event_name"] == "PathClaimRegistrationBlocked"
    assert row["severity"] == "WARN"
    envelope = json.loads(row["envelope"])
    assert envelope["context"]["reason"] == "covered-by-test"
