"""The session-owned strategy-document lock: ownership, authority, release."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    COORDINATOR_SESSION as COORDINATOR,
    LOCKED_DOC as DOC,
    WORKER_SESSION as WORKER,
    lock_document as _lock,
    seed_session as _seed_session,
    seed_strategy_doc as _seed_doc,
    strategy_test_database,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty
from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.strategy_coordination import append_strategy_coordination
from yoke_core.domain.strategy_docs import (
    StrategyDocConflictError,
    get_doc,
    replace_doc,
)
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimAuthorizationError,
    StrategyDocClaimConflictError,
    StrategyExecutionLinkError,
    active_strategy_doc_claim,
    authorize_strategy_doc_write,
    list_strategy_doc_claims,
    release_session_doc_claim,
)


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with strategy_test_database(tmp_path, monkeypatch) as db_path:
        yield db_path


def test_itemless_lock_is_session_owned_and_visible_in_the_listing(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        claim = _lock(conn)

        assert claim["owner_kind"] == "session"
        assert claim["owner_session_id"] == COORDINATOR
        assert claim["owner_item_id"] is None
        assert claim["public_ref"] is None
        assert COORDINATOR in claim["holder_label"]

        listed = list_strategy_doc_claims(conn, project_id=1)
        assert [row["strategy_doc_slug"] for row in listed] == [DOC]
        assert listed[0]["owner_kind"] == "session"
    finally:
        conn.close()


def test_itemless_lock_authorizes_only_its_own_session_to_revise(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _lock(conn)

        assert authorize_strategy_doc_write(
            conn,
            project_id=1,
            slug=DOC,
            session_id=COORDINATOR,
        )
        with pytest.raises(StrategyDocClaimAuthorizationError):
            authorize_strategy_doc_write(
                conn,
                project_id=1,
                slug=DOC,
                session_id=WORKER,
            )
    finally:
        conn.close()


def test_only_the_holding_session_releases_its_lock(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seed_session(conn, WORKER)
        _lock(conn)

        with pytest.raises(StrategyDocClaimAuthorizationError):
            release_session_doc_claim(
                conn,
                project_id=1,
                slug=DOC,
                session_id=WORKER,
                actor_id=1,
                reason="not mine to release",
            )
        with pytest.raises(StrategyExecutionLinkError):
            release_session_doc_claim(
                conn,
                project_id=1,
                slug="MASTER-PLAN",
                session_id=COORDINATOR,
                actor_id=1,
                reason="no lock there",
            )
    finally:
        conn.close()


def test_paired_document_refuses_direct_release_while_seat_is_active(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        steering = acquire_steering(
            conn,
            session_id=COORDINATOR,
            project_id=1,
            document=DOC,
            actor_id=1,
        )
        with pytest.raises(
            StrategyDocClaimAuthorizationError,
            match=f"yoke claims steering release {steering['id']}",
        ):
            release_session_doc_claim(
                conn,
                project_id=1,
                slug=DOC,
                session_id=COORDINATOR,
                actor_id=1,
                reason="split the pair",
            )
    finally:
        conn.close()


def test_a_second_session_cannot_take_a_held_document(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seed_session(conn, WORKER)
        first = _lock(conn)
        assert _lock(conn)["id"] == first["id"]

        with pytest.raises(StrategyDocClaimConflictError) as refusal:
            _lock(conn, WORKER)
        assert COORDINATOR in str(refusal.value)
    finally:
        conn.close()


def test_the_stale_sweep_reclaims_an_abandoned_lock(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seed_session(conn, WORKER)
        _lock(conn)

        reclaim_stale_session(conn, COORDINATOR)

        assert active_strategy_doc_claim(conn, project_id=1, slug=DOC) is None
        history = list_strategy_doc_claims(conn, project_id=1, active_only=False)
        assert history[0]["release_reason"] == "reclaimed"
        assert _lock(conn, WORKER)["owner_session_id"] == WORKER
    finally:
        conn.close()


def test_a_held_lock_keeps_the_soft_session_end_from_ending_it(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _lock(conn)

        result = end_session_if_empty(conn, COORDINATOR)
        assert result["status"] == "has_document_locks"
        assert result["ended"] is False
        assert result["active_document_lock_count"] == 1
        assert active_strategy_doc_claim(conn, project_id=1, slug=DOC) is not None
    finally:
        conn.close()


def test_an_ended_session_cannot_take_a_lock(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        conn.execute(
            "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
            (iso8601_now(), COORDINATOR),
        )
        conn.commit()

        with pytest.raises(StrategyDocClaimAuthorizationError):
            _lock(conn)
    finally:
        conn.close()


def test_non_holder_cannot_replace_while_coordination_append_keeps_holds(
    tmp_db: str,
) -> None:
    """Owner handoff and conflicting remote update stay on live surfaces.

    A held document refuses replace authority to anyone else. A stale
    compare-and-swap leaves standing text untouched. Coordination append
    is the proposal path: it adds an entry without granting replace.
    """
    conn = connect_test_db(tmp_db)
    try:
        standing = "# Area plan\n\nStanding hold: do not skip CI.\n"
        _seed_doc(conn, DOC, standing)
        _seed_session(conn, COORDINATOR)
        _seed_session(conn, WORKER)
        _lock(conn)

        assert authorize_strategy_doc_write(
            conn, project_id=1, slug=DOC, session_id=COORDINATOR,
        )
        with pytest.raises(StrategyDocClaimAuthorizationError):
            authorize_strategy_doc_write(
                conn, project_id=1, slug=DOC, session_id=WORKER,
            )

        live = get_doc(conn, 1, DOC)
        with pytest.raises(StrategyDocConflictError):
            replace_doc(
                conn,
                1,
                DOC,
                standing + "stale overwrite\n",
                2,
                base_updated_at="2000-01-01T00:00:00Z",
            )
        after_conflict = get_doc(conn, 1, DOC)
        assert "Standing hold: do not skip CI." in after_conflict["content"]
        assert "stale overwrite" not in after_conflict["content"]
        assert after_conflict["content"] == live["content"]

        appended = append_strategy_coordination(
            conn,
            project_id=1,
            slug=DOC,
            section="Live Status",
            entry="- proposed condensation preserves the standing hold",
            actor_id=2,
            session_id=WORKER,
        )
        assert appended["slug"] == DOC
        body = get_doc(conn, 1, DOC)["content"]
        assert "Standing hold: do not skip CI." in body
        assert "proposed condensation preserves the standing hold" in body
    finally:
        conn.close()
