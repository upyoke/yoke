"""Advanced coordination-lease tests — actor / heartbeat / list / events.

Split out of :mod:`test_coordination_leases` so each authored test file stays
under the 350-line file-line cap. Together these cover AC-13's surface: actor
attribution, heartbeat updates, idempotent release (covered in the original
suite), operator release (also original), stale/orphan reporting, list
helpers, concurrent lease conflict, and the new lifecycle-event emissions.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import coordination_leases
from runtime.api.domain.test_coordination_leases import _seed_projects
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture()
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        _seed_projects(path)
        yield path


def _connect(db_path: str):
    return connect_test_db(db_path)


class TestActorAttribution:
    def test_acquire_records_actor_id(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
                actor_id="ben",
            )
            assert lease.actor_id == "ben"
            assert lease.heartbeat_at == lease.acquired_at
        finally:
            conn.close()

    def test_acquire_actor_id_optional(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "EXAMPLE_OP:x", "sess-1",
            )
            assert lease.actor_id is None
            assert lease.heartbeat_at is not None
        finally:
            conn.close()

    def test_concurrent_acquire_surfaces_holder(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-a",
                actor_id="ben",
            )
            with pytest.raises(coordination_leases.LeaseHeldError) as exc:
                coordination_leases.acquire_lease(
                    conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-b",
                    actor_id="other",
                )
            assert "sess-a" in str(exc.value)
        finally:
            conn.close()


class TestHeartbeat:
    def test_heartbeat_refreshes_timestamp(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
            )
            refreshed = coordination_leases.heartbeat_lease(
                conn, lease.id, now="2099-01-01T00:00:00Z",
            )
            assert refreshed.heartbeat_at == "2099-01-01T00:00:00Z"
            assert refreshed.acquired_at == lease.acquired_at
        finally:
            conn.close()

    def test_heartbeat_refuses_released(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
            )
            coordination_leases.release_lease(conn, lease.id, "completed")
            with pytest.raises(coordination_leases.LeaseReleasedError):
                coordination_leases.heartbeat_lease(conn, lease.id)
        finally:
            conn.close()

    def test_heartbeat_refuses_missing(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            with pytest.raises(coordination_leases.LeaseNotFoundError):
                coordination_leases.heartbeat_lease(conn, 9999)
        finally:
            conn.close()


class TestListing:
    def test_list_filters_by_project_and_session(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
            )
            coordination_leases.acquire_lease(
                conn, "externalwebapp", "EXAMPLE_OP:x", "sess-2",
            )
            project = coordination_leases.list_leases(
                conn, project_id="yoke",
            )
            assert {row.session_id for row in project} == {"sess-1"}
            session = coordination_leases.list_leases(
                conn, session_id="sess-2",
            )
            assert {row.project_id for row in session} == {2}
        finally:
            conn.close()

    def test_list_active_only_excludes_released(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
            )
            coordination_leases.release_lease(conn, lease.id, "completed")
            coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-2",
            )
            actives = coordination_leases.list_leases(conn, active_only=True)
            assert len(actives) == 1
            assert actives[0].session_id == "sess-2"
        finally:
            conn.close()

    def test_stale_candidates_uses_threshold(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-stale",
                now="2026-01-01T00:00:00Z",
            )
            coordination_leases.acquire_lease(
                conn, "yoke", "EXAMPLE_OP:x", "sess-fresh",
                now="2099-01-01T00:00:00Z",
            )
            stale = coordination_leases.stale_lease_candidates(
                conn, threshold_iso="2030-01-01T00:00:00Z",
            )
            keys = {row.lease_key for row in stale}
            assert keys == {"LIVE_DB_MIGRATION:primary"}
        finally:
            conn.close()


class TestEventEmission:
    def _capture_events(self, monkeypatch) -> list:
        calls: list = []

        def _fake_emit(name, **kwargs):
            calls.append({"name": name, **kwargs})

        monkeypatch.setattr(
            "yoke_core.domain.events.emit_event", _fake_emit,
        )
        return calls

    def test_acquire_emits_lease_acquired(
        self, db_path: str, monkeypatch,
    ) -> None:
        calls = self._capture_events(monkeypatch)
        conn = _connect(db_path)
        try:
            coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
                actor_id="ben",
            )
        finally:
            conn.close()
        names = [call["name"] for call in calls]
        assert coordination_leases.LEASE_ACQUIRED_EVENT in names

    def test_heartbeat_emits_lease_heartbeated(
        self, db_path: str, monkeypatch,
    ) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
            )
            calls = self._capture_events(monkeypatch)
            coordination_leases.heartbeat_lease(conn, lease.id)
        finally:
            conn.close()
        names = [call["name"] for call in calls]
        assert coordination_leases.LEASE_HEARTBEATED_EVENT in names

    def test_release_emits_lease_released(
        self, db_path: str, monkeypatch,
    ) -> None:
        conn = _connect(db_path)
        try:
            lease = coordination_leases.acquire_lease(
                conn, "yoke", "LIVE_DB_MIGRATION:primary", "sess-1",
            )
            calls = self._capture_events(monkeypatch)
            coordination_leases.release_lease(conn, lease.id, "completed")
        finally:
            conn.close()
        names = [call["name"] for call in calls]
        assert coordination_leases.LEASE_RELEASED_EVENT in names
