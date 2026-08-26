"""Coordination claims: contention evidence, heartbeat, listing, events.

Split out of :mod:`test_coordination_claims` so each authored test file
stays under the file-line cap.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import coordination_claims
from yoke_core.domain.coordination_claims_listing import (
    list_claims,
    stale_claim_candidates,
)
from runtime.api.domain.coordination_claim_test_support import (
    MODEL,
    PROJECT_OTHER,
    PROJECT_YOKE,
    migration_target,
    qa_target,
    seed_project,
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture()
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        conn = connect_test_db(path)
        try:
            seed_project(conn, PROJECT_YOKE, "yoke")
            seed_project(conn, PROJECT_OTHER, "externalwebapp")
            for session_id in ("sess-1", "sess-2", "sess-a", "sess-b", "sess-waiting"):
                seed_session(conn, session_id)
            seed_session(conn, "sess-other", PROJECT_OTHER)
            seed_session(conn, "sess-dead", PROJECT_YOKE, ended=True)
        finally:
            conn.close()
        yield path


def _connect(db_path: str):
    return connect_test_db(db_path)


class TestContentionEvidence:
    def test_concurrent_acquire_surfaces_the_holder(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, qa_target(), "sess-a")
            with pytest.raises(
                coordination_claims.CoordinationClaimHeldError
            ) as exc:
                coordination_claims.acquire(conn, qa_target(), "sess-b")
            message = str(exc.value)
            assert "sess-a" in message
            assert "heartbeat age" in message
            assert "yoke coordination-claim release" in message
        finally:
            conn.close()

    def test_dead_holder_refuses_the_wait_with_the_operator_recipe(
        self, db_path: str
    ) -> None:
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(
                conn, qa_target(), "sess-dead", now="2020-01-01T00:00:00Z"
            )
            with pytest.raises(
                coordination_claims.CoordinationClaimStaleHolderError,
                match="wait refused",
            ) as exc:
                coordination_claims.acquire(conn, qa_target(), "sess-waiting")
            message = str(exc.value)
            assert "held by session sess-dead" in message
            assert "--key QA_HOST:mac-mini-lab" in message
            assert "--reason 'stale holder confirmed'" in message
        finally:
            conn.close()

    def test_item_owned_territory_never_reports_stale(self, db_path: str) -> None:
        """No session liveness applies: the item, not a session, is the holder."""
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(
                conn, migration_target(7), "sess-dead", now="2020-01-01T00:00:00Z"
            )
            with pytest.raises(
                coordination_claims.CoordinationClaimHeldError
            ) as exc:
                coordination_claims.acquire(conn, migration_target(8), "sess-a")
            assert not isinstance(
                exc.value, coordination_claims.CoordinationClaimStaleHolderError
            )
            assert "held by item 7" in str(exc.value)
        finally:
            conn.close()


class TestHeartbeat:
    def test_heartbeat_refreshes_the_timestamp(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-1")
            refreshed = coordination_claims.heartbeat(
                conn, claim.id, now="2099-01-01T00:00:00Z"
            )
            assert refreshed.last_heartbeat == "2099-01-01T00:00:00Z"
            assert refreshed.claimed_at == claim.claimed_at
        finally:
            conn.close()

    def test_heartbeat_refuses_missing(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            with pytest.raises(
                coordination_claims.CoordinationClaimNotFoundError
            ):
                coordination_claims.heartbeat(conn, 9999)
        finally:
            conn.close()


class TestListing:
    def test_list_filters_by_project_and_session(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, migration_target(7), "sess-1")
            coordination_claims.acquire(
                conn, migration_target(8, project_id=PROJECT_OTHER), "sess-other"
            )
            project = list_claims(conn, project_id="yoke")
            assert {row.session_id for row in project} == {"sess-1"}
            session = list_claims(conn, session_id="sess-other")
            assert {row.project_id for row in session} == {PROJECT_OTHER}
        finally:
            conn.close()

    def test_list_filters_by_key_and_owning_item(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, migration_target(7), "sess-1")
            coordination_claims.acquire(conn, qa_target(), "sess-2")
            by_key = list_claims(conn, key=f"LIVE_DB_MIGRATION:{MODEL}")
            assert {row.key for row in by_key} == {f"LIVE_DB_MIGRATION:{MODEL}"}
            by_item = list_claims(conn, owner_item_id=7)
            assert {row.owner_item_id for row in by_item} == {7}
        finally:
            conn.close()

    def test_list_active_only_excludes_released(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-1")
            coordination_claims.release(conn, claim.id, "completed")
            coordination_claims.acquire(conn, qa_target(), "sess-2")
            actives = list_claims(conn, active_only=True)
            assert len(actives) == 1
            assert actives[0].session_id == "sess-2"
        finally:
            conn.close()

    def test_list_ignores_backlog_claims(self, db_path: str) -> None:
        """Only shared-operation kinds belong to this surface."""
        from yoke_core.domain.steering_claims import acquire as acquire_steering

        conn = _connect(db_path)
        try:
            acquire_steering(
                conn, session_id="sess-1", project_id=PROJECT_YOKE, reason="steer"
            )
            assert list_claims(conn) == []
        finally:
            conn.close()

    def test_stale_candidates_use_the_threshold(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(
                conn, qa_target(), "sess-1", now="2026-01-01T00:00:00Z"
            )
            coordination_claims.acquire(
                conn, migration_target(7), "sess-2", now="2099-01-01T00:00:00Z"
            )
            stale = stale_claim_candidates(
                conn, threshold_iso="2030-01-01T00:00:00Z"
            )
            assert {row.key for row in stale} == {"QA_HOST:mac-mini-lab"}
        finally:
            conn.close()


class TestEventEmission:
    def _capture(self, monkeypatch) -> list:
        calls: list = []
        monkeypatch.setattr(
            "yoke_core.domain.events.emit_event",
            lambda name, **kwargs: calls.append({"name": name, **kwargs}),
        )
        return calls

    def test_acquire_emits_the_acquired_event(
        self, db_path: str, monkeypatch
    ) -> None:
        calls = self._capture(monkeypatch)
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, qa_target(), "sess-1")
        finally:
            conn.close()
        assert coordination_claims.LEASE_ACQUIRED_EVENT in [
            call["name"] for call in calls
        ]

    def test_heartbeat_emits_the_heartbeat_event(
        self, db_path: str, monkeypatch
    ) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-1")
            calls = self._capture(monkeypatch)
            coordination_claims.heartbeat(conn, claim.id)
        finally:
            conn.close()
        assert coordination_claims.LEASE_HEARTBEATED_EVENT in [
            call["name"] for call in calls
        ]

    def test_release_emits_the_released_event(
        self, db_path: str, monkeypatch
    ) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-1")
            calls = self._capture(monkeypatch)
            coordination_claims.release(conn, claim.id, "completed")
        finally:
            conn.close()
        assert coordination_claims.LEASE_RELEASED_EVENT in [
            call["name"] for call in calls
        ]
