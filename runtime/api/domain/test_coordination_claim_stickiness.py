"""Sticky claim kinds survive what reclaims a liveness-bound one.

The stale-session sweep, the session-end release, and the claim-free end
check exist because a session that goes quiet cannot finish its backlog
work. A migration mid-authorship and a physical host mid-suite keep
operating regardless, so reclaiming those hands a live resource to a
second holder. These tests pin that difference at every surface that
releases claims by session.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import coordination_claims
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.strategy_docs_defaults import seed_default_docs
from yoke_core.domain.work_claim_targets import (
    STICKY_TARGET_KINDS,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    TARGET_KIND_QA_ADMISSION,
    TARGET_KIND_ROUTE_QUALIFICATION,
    is_sticky,
)
from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    migration_target,
    qa_target,
    qualification_target,
    seed_project,
    seed_session,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

HOLDER = "sess-holder"


@pytest.fixture()
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        conn = connect_test_db(path)
        try:
            seed_project(conn, PROJECT_YOKE, "yoke")
            seed_session(conn, HOLDER)
        finally:
            conn.close()
        yield path


def _connect(db_path: str):
    return connect_test_db(db_path)


def _hold_everything(conn) -> dict[str, int]:
    """Take one claim of every kind a single session can hold."""
    return {
        TARGET_KIND_MIGRATION_SERIALIZATION: coordination_claims.acquire(
            conn, migration_target(7), HOLDER
        ).id,
        TARGET_KIND_QA_ADMISSION: coordination_claims.acquire(
            conn, qa_target(), HOLDER
        ).id,
        TARGET_KIND_ROUTE_QUALIFICATION: coordination_claims.acquire(
            conn, qualification_target(), HOLDER
        ).id,
    }


def _assert_sticky_survived(conn, claims: dict[str, int]) -> None:
    for kind, claim_id in claims.items():
        settled = coordination_claims.get_claim(conn, claim_id)
        assert settled.is_active is is_sticky(kind), (
            f"{kind} should be {'held' if is_sticky(kind) else 'released'}"
        )


class TestPolicy:
    def test_the_sticky_set_is_exactly_the_resource_kinds(self) -> None:
        assert STICKY_TARGET_KINDS == {
            TARGET_KIND_MIGRATION_SERIALIZATION,
            TARGET_KIND_QA_ADMISSION,
        }
        assert not is_sticky(TARGET_KIND_ROUTE_QUALIFICATION)
        assert not is_sticky("item")


class TestStaleSessionSweep:
    def test_qa_and_migration_claims_survive_stale_session_reclaim(
        self, db_path: str
    ) -> None:
        from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session

        conn = _connect(db_path)
        try:
            claims = _hold_everything(conn)
            seed_default_docs(conn, PROJECT_YOKE, "Yoke")
            acquire_steering(
                conn, session_id=HOLDER, project_id=PROJECT_YOKE, reason="steer"
            )
            reclaim_stale_session(conn, HOLDER)
            _assert_sticky_survived(conn, claims)
        finally:
            conn.close()


class TestSessionEndRelease:
    @pytest.mark.parametrize("release_claims", [False, True])
    def test_qa_and_migration_claims_survive_session_end(
        self, db_path: str, release_claims: bool
    ) -> None:
        from yoke_core.domain.sessions_render_end import end_session

        conn = _connect(db_path)
        try:
            claims = _hold_everything(conn)
            result = end_session(conn, HOLDER, release_claims=release_claims)
            assert result["ended_at"] is not None
            _assert_sticky_survived(conn, claims)
        finally:
            conn.close()

    def test_release_all_leaves_the_sticky_holds_alone(self, db_path: str) -> None:
        from yoke_core.domain.sessions_lifecycle_release_bulk import (
            release_all_claims,
        )

        conn = _connect(db_path)
        try:
            claims = _hold_everything(conn)
            release_all_claims(conn, HOLDER)
            _assert_sticky_survived(conn, claims)
        finally:
            conn.close()


class TestHarnessSessionCommands:
    @pytest.mark.parametrize("command_name", ["release_all", "reclaim"])
    def test_session_scoped_commands_preserve_sticky_claims(
        self, db_path: str, command_name: str, monkeypatch
    ) -> None:
        from yoke_core.hooks import sessions_claims

        conn = _connect(db_path)
        try:
            claims = _hold_everything(conn)
            monkeypatch.setattr(sessions_claims, "_emit_event", lambda *a, **k: None)
            if command_name == "release_all":
                sessions_claims.cmd_release_all(conn, HOLDER)
            else:
                sessions_claims.cmd_reclaim(conn, HOLDER)
            _assert_sticky_survived(conn, claims)
        finally:
            conn.close()


class TestClaimFreeEndCheck:
    def test_a_sticky_hold_does_not_block_a_clean_session_end(
        self, db_path: str
    ) -> None:
        """Otherwise a session that rehearsed a migration could never end."""
        from yoke_core.domain.sessions_render_end_if_empty import (
            end_session_if_empty,
        )

        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, migration_target(7), HOLDER)
            coordination_claims.acquire(conn, qa_target(), HOLDER)
            result = end_session_if_empty(conn, HOLDER)
            assert result["ended"] is True
            assert result["active_claim_count"] == 0
        finally:
            conn.close()

    def test_a_liveness_bound_hold_still_blocks(self, db_path: str) -> None:
        from yoke_core.domain.sessions_render_end_if_empty import (
            end_session_if_empty,
        )

        conn = _connect(db_path)
        try:
            coordination_claims.acquire(conn, qualification_target(), HOLDER)
            result = end_session_if_empty(conn, HOLDER)
            assert result["status"] == "has_claims"
            assert result["ended"] is False
        finally:
            conn.close()
