"""Race coverage for session reactivation telemetry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.sessions import SessionError, register_session


class _ZeroRowcount:
    rowcount = 0


class _RaceConn:
    """Fake the losing side of concurrent reactivation."""

    def execute(self, sql, params=()):  # noqa: ARG002
        if "information_schema.columns" in sql or "pg_catalog.pg_attribute" in sql:
            # episode-column introspection (register_session) — report the
            # column absent so the fake's SQL surface stays minimal.
            return _EmptyResult()
        if sql.startswith("SELECT 1 FROM projects"):
            return _RowResult({"id": 1})
        if sql.startswith("INSERT INTO harness_sessions"):
            raise db_backend.integrity_error_types()[0]("duplicate session")
        if "SELECT ended_at, model, actor_id, execution_lane, project_id" in sql:
            return _RowResult(
                {
                    "ended_at": "2026-06-06T00:00:00Z",
                    "model": "gpt",
                    "actor_id": None,
                    "execution_lane": "primary",
                    "project_id": 1,
                }
            )
        if "UPDATE harness_sessions" in sql and "ended_at IS NOT NULL" in sql:
            return _ZeroRowcount()
        raise AssertionError(f"unexpected SQL: {sql}")

    def commit(self):
        raise AssertionError("losing reactivation must not commit")

    def rollback(self):
        pass


class _EmptyResult:
    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _RowResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


def test_reactivation_loser_does_not_emit_started_event():
    emitted = []
    conn = _RaceConn()

    with patch(
        "yoke_core.domain.sessions_lifecycle_registry._resolve_session_actor_id",
        return_value=None,
    ), patch(
        "yoke_core.domain.sessions_analytics._emit_session_event",
        side_effect=lambda *args, **kwargs: emitted.append((args, kwargs)),
    ):
        with pytest.raises(SessionError) as exc_info:
            register_session(
                conn,
                session_id="race-sess",
                executor="codex",
                provider="openai",
                model="gpt",
                workspace="/repo",
                project_id=1,
            )

    assert exc_info.value.code == "SESSION_EXISTS"
    assert emitted == []
