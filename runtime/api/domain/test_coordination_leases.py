"""Tests for the coordination-lease primitive (governed DB-mutation contract)."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import coordination_leases
from yoke_core.domain.schema_common import _get_columns, _table_exists
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _seed_projects(path: str) -> None:
    conn = connect_test_db(path)
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}), ({p}, {p}, {p}, {p}) "
            "ON CONFLICT (id) DO NOTHING",
            (
                1, "yoke", "Yoke", "2026-04-23T00:00:00Z",
                2, "externalwebapp", "ExternalWebapp", "2026-04-23T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        _seed_projects(path)
        yield path


def _connect(db_path: str):
    return connect_test_db(db_path)


class TestSchema:
    def test_coordination_leases_table_exists(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            assert _table_exists(conn, "coordination_leases")
            cols = set(_get_columns(conn, "coordination_leases"))
            assert cols == {
                "id", "project_id", "lease_key", "session_id",
                "actor_id", "acquired_at", "heartbeat_at",
                "released_at", "release_reason",
            }
        finally:
            conn.close()

    def test_partial_unique_index_on_live_rows(self, db_path: str) -> None:
        """Only one live lease per (project, key); released rows don't block re-acquire."""
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-a"
            )
            assert lease.is_active

            # Second acquire under a different session must fail
            with pytest.raises(coordination_leases.LeaseHeldError):
                coordination_leases.acquire_lease(
                    conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-b"
                )

            # Release, then re-acquire must succeed
            coordination_leases.release_lease(conn, lease.id, "completed")
            new_lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-b"
            )
            assert new_lease.is_active
            assert new_lease.id != lease.id
        finally:
            conn.close()


class TestAcquireRelease:
    def test_acquire_populates_row(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1"
            )
            assert lease.project_id == 1
            assert lease.lease_key == "LIVE_DB_MIGRATION:primary"
            assert lease.session_id == "sess-1"
            assert lease.acquired_at.endswith("Z")
            assert lease.released_at is None
            assert lease.release_reason is None
        finally:
            conn.close()

    def test_active_lease_returns_none_when_free(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            assert coordination_leases.active_lease(conn, "yoke", "FEED") is None
        finally:
            conn.close()

    def test_active_lease_returns_latest_holder(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1"
            )
            held = coordination_leases.active_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary"
            )
            assert held is not None
            assert held.id == lease.id
        finally:
            conn.close()

    def test_release_is_idempotent(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1"
            )
            first = coordination_leases.release_lease(conn, lease.id, "completed")
            second = coordination_leases.release_lease(conn, lease.id, "again")
            assert first.released_at == second.released_at
            assert first.release_reason == "completed"
            assert second.release_reason == "completed"
        finally:
            conn.close()

    def test_get_lease_raises_not_found(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            with pytest.raises(coordination_leases.LeaseNotFoundError):
                coordination_leases.get_lease(conn, 9999)
        finally:
            conn.close()


class TestOperatorRelease:
    def _setup(self, db_path: str):
        conn = _connect(db_path)
        coordination_leases.acquire_lease(
            conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-wedged"
        )
        return db_path, conn

    def test_emits_warn_event_before_release(self, db_path: str) -> None:
        db_path, conn = self._setup(db_path)
        emit_calls = []
        try:
            def _fake_emit(**kwargs):
                emit_calls.append(kwargs)

            with mock.patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False):
                with mock.patch(
                    "yoke_core.domain.coordination_leases_operator._emit_operator_lease_release",
                    side_effect=lambda **kw: emit_calls.append(kw),
                ):
                    result = coordination_leases.operator_release(
                        conn,
                        project_id="yoke",
                        lease_key="LIVE_DB_MIGRATION:primary",
                        operator_reason="crashed apply-phase session",
                        session_id="sess-operator",
                    )

            assert result["released"] is True
            assert result["prior_session_id"] == "sess-wedged"
            assert result["operator_reason"] == "crashed apply-phase session"
            # Ledger-first: event emission happened before release took effect
            assert len(emit_calls) == 1
            context = emit_calls[0]["context"]
            assert context["project_id"] == 1
            assert context["lease_key"] == "LIVE_DB_MIGRATION:primary"
            assert context["operator_reason"] == "crashed apply-phase session"
            assert context["release_reason_intent"] == "operator-override"
        finally:
            conn.close()

    def test_release_reason_is_audit_preserving(self, db_path: str) -> None:
        db_path, conn = self._setup(db_path)
        try:
            coordination_leases.operator_release(
                conn,
                project_id="yoke",
                lease_key="LIVE_DB_MIGRATION:primary",
                operator_reason="crashed apply-phase session",
            )
            row = conn.execute(
                "SELECT released_at, release_reason FROM coordination_leases "
                "WHERE project_id = %s AND lease_key = %s",
                (1, "LIVE_DB_MIGRATION:primary"),
            ).fetchone()
            assert row["released_at"] is not None
            assert row["release_reason"].startswith("operator-override:")
            assert "crashed apply-phase session" in row["release_reason"]
        finally:
            conn.close()

    def test_rejects_hook_context(self, db_path: str) -> None:
        db_path, conn = self._setup(db_path)
        try:
            with mock.patch.dict(os.environ, {"YOKE_HOOK_EVENT": "SessionEnd"}):
                with pytest.raises(coordination_leases.LeaseHookContextError):
                    coordination_leases.operator_release(
                        conn,
                        project_id="yoke",
                        lease_key="LIVE_DB_MIGRATION:primary",
                        operator_reason="should not fire",
                    )
            # Lease must remain held after refusal
            still_held = coordination_leases.active_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary"
            )
            assert still_held is not None
            assert still_held.released_at is None
        finally:
            conn.close()

    def test_rejects_empty_operator_reason(self, db_path: str) -> None:
        db_path, conn = self._setup(db_path)
        try:
            with pytest.raises(coordination_leases.LeaseError):
                coordination_leases.operator_release(
                    conn,
                    project_id="yoke",
                    lease_key="LIVE_DB_MIGRATION:primary",
                    operator_reason="  ",
                )
        finally:
            conn.close()

    def test_raises_not_found_when_no_live_lease(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            with pytest.raises(coordination_leases.LeaseNotFoundError):
                coordination_leases.operator_release(
                    conn,
                    project_id="yoke",
                    lease_key="LIVE_DB_MIGRATION:primary",
                    operator_reason="no-op recovery",
                )
        finally:
            conn.close()
