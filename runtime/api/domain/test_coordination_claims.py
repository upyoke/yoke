"""Shared-operation coordination claims: exclusivity, lifecycle, recovery."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_core.domain import coordination_claims
from yoke_core.domain.coordination_claims_operator import operator_release
from runtime.api.domain.coordination_claim_test_support import (
    MODEL,
    PROJECT_OTHER,
    PROJECT_YOKE,
    migration_target,
    qa_target,
    qualification_target,
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
            for session_id in ("sess-a", "sess-b", "sess-wedged", "sess-operator"):
                seed_session(conn, session_id)
        finally:
            conn.close()
        yield path


def _connect(db_path: str):
    return connect_test_db(db_path)


class TestSchema:
    def test_one_live_claim_per_resource(self, db_path: str) -> None:
        """Released rows must not block the next acquire."""
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-a")
            assert claim.is_active

            with pytest.raises(coordination_claims.CoordinationClaimHeldError):
                coordination_claims.acquire(conn, qa_target(), "sess-b")

            coordination_claims.release(conn, claim.id, "completed")
            reacquired = coordination_claims.acquire(conn, qa_target(), "sess-b")
            assert reacquired.is_active
            assert reacquired.id != claim.id
        finally:
            conn.close()

    def test_migration_territory_conflicts_on_the_model_not_the_item(
        self, db_path: str
    ) -> None:
        """The owning item rides in scope but is not part of what is held."""
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, migration_target(7), "sess-a")
            with pytest.raises(coordination_claims.CoordinationClaimHeldError):
                coordination_claims.acquire(conn, migration_target(8), "sess-b")
        finally:
            conn.close()

    def test_migration_territory_is_scoped_per_project(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, migration_target(7), "sess-a")
            other = coordination_claims.acquire(
                conn, migration_target(8, project_id=PROJECT_OTHER), "sess-b"
            )
            assert other.is_active
        finally:
            conn.close()

    def test_one_machine_is_one_resource_across_projects(self, db_path: str) -> None:
        """A physical host has no project in scope, so it never forks."""
        conn = _connect(db_path)
        try:
            assert qa_target().project_id is None
            coordination_claims.acquire(conn, qa_target(), "sess-a")
            with pytest.raises(coordination_claims.CoordinationClaimHeldError):
                coordination_claims.acquire(conn, qa_target(), "sess-b")
        finally:
            conn.close()


class TestAcquireRelease:
    def test_acquire_populates_the_row(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(
                conn, migration_target(7), "sess-a", reason="migration-territory"
            )
            assert claim.project_id == PROJECT_YOKE
            assert claim.key == f"LIVE_DB_MIGRATION:{MODEL}"
            assert claim.session_id == "sess-a"
            assert claim.owner_item_id == 7
            assert claim.sticky is True
            assert claim.claimed_at.endswith("Z")
            assert claim.last_heartbeat == claim.claimed_at
            assert claim.released_at is None
        finally:
            conn.close()

    def test_actor_comes_from_the_holding_session(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-a")
            assert claim.actor_id == "2"
        finally:
            conn.close()

    def test_active_claim_returns_none_when_free(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            assert coordination_claims.active_claim(conn, qa_target()) is None
        finally:
            conn.close()

    def test_active_claim_returns_the_holder(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-a")
            held = coordination_claims.active_claim(conn, qa_target())
            assert held is not None and held.id == claim.id
        finally:
            conn.close()

    def test_heartbeat_refuses_a_released_claim(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-a")
            coordination_claims.release(conn, claim.id, "done")
            with pytest.raises(coordination_claims.CoordinationClaimReleasedError):
                coordination_claims.heartbeat(conn, claim.id)
        finally:
            conn.close()

    def test_release_is_idempotent(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-a")
            first = coordination_claims.release(conn, claim.id, "completed")
            second = coordination_claims.release(conn, claim.id, "again")
            assert first.released_at == second.released_at
            assert first.release_reason_intent == "completed"
            assert second.release_reason_intent == "completed"
        finally:
            conn.close()

    def test_release_keeps_the_caller_words_beside_the_enum(
        self, db_path: str
    ) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(conn, qa_target(), "sess-a")
            released = coordination_claims.release(
                conn, claim.id, "machine-qa-complete", canonical_reason="completed"
            )
            assert released.release_reason == "completed"
            assert released.release_reason_intent == "machine-qa-complete"
        finally:
            conn.close()

    def test_get_claim_raises_not_found(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            with pytest.raises(coordination_claims.CoordinationClaimNotFoundError):
                coordination_claims.get_claim(conn, 9999)
        finally:
            conn.close()

    def test_qualification_grants_are_not_sticky(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            claim = coordination_claims.acquire(
                conn, qualification_target(), "sess-a"
            )
            assert claim.sticky is False
        finally:
            conn.close()


class TestOperatorRelease:
    def _hold(self, db_path: str):
        conn = _connect(db_path)
        coordination_claims.acquire(conn, migration_target(7), "sess-wedged")
        return conn

    def test_emits_warn_event_before_release(self, db_path: str) -> None:
        conn = self._hold(db_path)
        emit_calls: list[dict] = []
        try:
            with mock.patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False):
                with mock.patch(
                    "yoke_core.domain.coordination_claims_operator."
                    "_emit_operator_release",
                    side_effect=lambda **kw: emit_calls.append(kw),
                ):
                    result = operator_release(
                        conn,
                        project_id="yoke",
                        key=f"LIVE_DB_MIGRATION:{MODEL}",
                        operator_reason="crashed apply-phase session",
                        session_id="sess-operator",
                    )

            assert result["released"] is True
            assert result["prior_session_id"] == "sess-wedged"
            assert result["operator_session_id"] == "sess-operator"
            assert len(emit_calls) == 1
            context = emit_calls[0]["context"]
            assert context["project_id"] == PROJECT_YOKE
            assert context["lease_key"] == f"LIVE_DB_MIGRATION:{MODEL}"
            assert context["prior_owner_item_id"] == 7
            assert context["operator_reason"] == "crashed apply-phase session"
            assert context["release_reason_intent"] == "operator-override"
        finally:
            conn.close()

    def test_operator_reason_stays_on_the_row(self, db_path: str) -> None:
        conn = self._hold(db_path)
        try:
            result = operator_release(
                conn,
                project_id="yoke",
                key=f"LIVE_DB_MIGRATION:{MODEL}",
                operator_reason="crashed apply-phase session",
                session_id="sess-operator",
            )
            settled = coordination_claims.get_claim(conn, result["claim_id"])
            assert settled.released_at is not None
            assert settled.release_reason == "released"
            assert settled.release_reason_intent.startswith("operator-override:")
            assert "crashed apply-phase session" in settled.release_reason_intent
        finally:
            conn.close()

    def test_resolves_operator_session_from_ambient_identity(
        self, db_path: str
    ) -> None:
        conn = self._hold(db_path)
        try:
            with mock.patch(
                "yoke_core.domain.coordination_claims_operator."
                "resolve_ambient_session_id",
                return_value="sess-operator",
            ):
                result = operator_release(
                    conn,
                    project_id="yoke",
                    key=f"LIVE_DB_MIGRATION:{MODEL}",
                    operator_reason="crashed apply-phase session",
                )
            assert result["operator_session_id"] == "sess-operator"
        finally:
            conn.close()

    def test_rejects_hook_context(self, db_path: str) -> None:
        conn = self._hold(db_path)
        try:
            with mock.patch.dict(os.environ, {"YOKE_HOOK_EVENT": "SessionEnd"}):
                with pytest.raises(
                    coordination_claims.CoordinationClaimHookContextError
                ):
                    operator_release(
                        conn,
                        project_id="yoke",
                        key=f"LIVE_DB_MIGRATION:{MODEL}",
                        operator_reason="should not fire",
                    )
            still_held = coordination_claims.active_claim(conn, migration_target(7))
            assert still_held is not None and still_held.released_at is None
        finally:
            conn.close()

    def test_rejects_empty_operator_reason(self, db_path: str) -> None:
        conn = self._hold(db_path)
        try:
            with pytest.raises(coordination_claims.CoordinationClaimError):
                operator_release(
                    conn,
                    project_id="yoke",
                    key=f"LIVE_DB_MIGRATION:{MODEL}",
                    operator_reason="  ",
                    session_id="sess-operator",
                )
        finally:
            conn.close()

    def test_raises_not_found_when_nothing_is_held(self, db_path: str) -> None:
        conn = _connect(db_path)
        try:
            with pytest.raises(coordination_claims.CoordinationClaimNotFoundError):
                operator_release(
                    conn,
                    project_id="yoke",
                    key=f"LIVE_DB_MIGRATION:{MODEL}",
                    operator_reason="no-op recovery",
                    session_id="sess-operator",
                )
        finally:
            conn.close()

    def test_refuses_when_the_operator_session_is_unknown(
        self, db_path: str, monkeypatch
    ) -> None:
        conn = self._hold(db_path)
        monkeypatch.setattr(
            "yoke_core.domain.coordination_claims_operator."
            "resolve_ambient_session_id",
            lambda: None,
        )
        try:
            with pytest.raises(
                coordination_claims.CoordinationClaimError, match="operator session"
            ):
                operator_release(
                    conn,
                    project_id="yoke",
                    key=f"LIVE_DB_MIGRATION:{MODEL}",
                    operator_reason="crashed apply-phase session",
                )
        finally:
            conn.close()
