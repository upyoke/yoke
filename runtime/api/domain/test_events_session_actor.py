"""Unit tests for session→actor enrichment + provenance marking on events.

Uses a disposable Postgres database carrying only a minimal
``harness_sessions`` table so the row-found / no-row / null-actor states
are exercised deterministically against the native authority dialect.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.events_session_actor import (
    PROVENANCE_UNVERIFIED_KEY,
    apply_session_actor_id,
    session_actor_lookup,
)
from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)


@pytest.fixture()
def conn():
    connection = connect_disposable_test_db()
    connection.execute(
        "CREATE TABLE harness_sessions (session_id TEXT, actor_id INTEGER)"
    )
    connection.execute(
        "INSERT INTO harness_sessions VALUES ('s-registered', 7)"
    )
    connection.execute(
        "INSERT INTO harness_sessions VALUES ('s-null-actor', NULL)"
    )
    yield connection
    connection.close()


def _envelope(session_id, *, actor_id=None, context=None):
    return {
        "session_id": session_id,
        "actor_id": actor_id,
        "context": {} if context is None else context,
    }


class TestSessionActorLookup:
    def test_registered_session_with_actor(self, conn):
        assert session_actor_lookup(conn, "s-registered") == (True, 7)

    def test_registered_session_with_null_actor(self, conn):
        assert session_actor_lookup(conn, "s-null-actor") == (True, None)

    def test_unregistered_session_is_positive_no_row(self, conn):
        assert session_actor_lookup(conn, "s-ghost") == (False, None)

    def test_broken_schema_reports_unknown(self):
        bare = connect_disposable_test_db()  # no harness_sessions table
        try:
            assert session_actor_lookup(bare, "s-1") == (None, None)
        finally:
            bare.close()


class TestApplySessionActorId:
    def test_registered_session_enriches_actor_without_marking(self, conn):
        envelope = _envelope("s-registered")
        apply_session_actor_id(envelope, conn=conn)
        assert envelope["actor_id"] == 7
        assert PROVENANCE_UNVERIFIED_KEY not in envelope["context"]

    def test_null_actor_row_is_registered_not_marked(self, conn):
        envelope = _envelope("s-null-actor")
        apply_session_actor_id(envelope, conn=conn)
        assert envelope["actor_id"] is None
        assert PROVENANCE_UNVERIFIED_KEY not in envelope["context"]

    def test_unregistered_session_marks_provenance(self, conn):
        envelope = _envelope("s-ghost")
        apply_session_actor_id(envelope, conn=conn)
        assert envelope["actor_id"] is None
        assert envelope["context"][PROVENANCE_UNVERIFIED_KEY] is True

    def test_marking_survives_missing_context_dict(self, conn):
        envelope = {"session_id": "s-ghost", "actor_id": None, "context": None}
        apply_session_actor_id(envelope, conn=conn)
        assert envelope["context"][PROVENANCE_UNVERIFIED_KEY] is True

    def test_failed_lookup_marks_nothing(self):
        bare = connect_disposable_test_db()
        try:
            envelope = _envelope("s-1")
            apply_session_actor_id(envelope, conn=bare)
            assert PROVENANCE_UNVERIFIED_KEY not in envelope["context"]
        finally:
            bare.close()

    def test_explicit_actor_skips_probe_entirely(self):
        class _Boom:
            def execute(self, *_a, **_k):
                raise AssertionError("must not probe when actor is explicit")

        envelope = _envelope("s-registered", actor_id=42)
        apply_session_actor_id(envelope, conn=_Boom())
        assert envelope["actor_id"] == 42

    def test_unknown_and_blank_sessions_skip_probe(self):
        class _Boom:
            def execute(self, *_a, **_k):
                raise AssertionError("must not probe a sessionless event")

        for sid in ("", "unknown", None):
            envelope = _envelope(sid)
            apply_session_actor_id(envelope, conn=_Boom())
            assert envelope["actor_id"] is None
