"""A document lock and the Blitz executing it exclude each other both ways."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    COORDINATOR_SESSION as COORDINATOR,
    LOCKED_DOC as DOC,
    WORKER_SESSION as WORKER,
    lock_document as _lock,
    seed_blitz_item as _seed_blitz_item,
    seed_linked_blitz as _seeded_blitz,
    seed_session as _seed_session,
    seed_session_claim as _seed_session_claim,
    seed_strategy_doc as _seed_doc,
    strategy_test_database,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.sessions_lifecycle_claim import SessionError, claim_work
from yoke_core.domain.strategy_execution import (
    StrategyDocClaimConflictError,
    acquire_strategy_doc_claim,
    active_strategy_doc_claim,
    link_execution_document,
    release_session_doc_claim,
)
from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with strategy_test_database(tmp_path, monkeypatch) as db_path:
        yield db_path


def test_itemless_lock_refuses_claiming_the_blitz_and_names_the_holder(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seed_session(conn, WORKER)
        _lock(conn)
        _seeded_blitz(conn, 3101)

        with pytest.raises(SessionError) as refusal:
            claim_work(
                conn,
                session_id=WORKER,
                target=make_item_target(3101),
                reason="execute the Blitz",
            )
        assert refusal.value.code == "DOCUMENT_LOCKED"
        assert COORDINATOR in str(refusal.value)
        assert DOC in str(refusal.value)
    finally:
        conn.close()


def test_itemless_lock_refuses_the_blitz_document_activation(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _lock(conn)
        _seed_blitz_item(conn, 3102, 3102)
        _seed_session_claim(conn, 3102, WORKER)
        link_execution_document(
            conn,
            item_id=3102,
            project_id=1,
            slug=DOC,
            actor_id=1,
            session_id=WORKER,
        )

        with pytest.raises(StrategyDocClaimConflictError) as refusal:
            acquire_strategy_doc_claim(
                conn,
                item_id=3102,
                session_id=WORKER,
                actor_id=1,
            )
        assert COORDINATOR in str(refusal.value)
    finally:
        conn.close()


def test_live_blitz_without_a_document_claim_refuses_the_itemless_lock(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seeded_blitz(conn, 3103)

        with pytest.raises(StrategyDocClaimConflictError) as refusal:
            _lock(conn)
        assert "3103" in str(refusal.value) or "YOK-3103" in str(refusal.value)
        assert active_strategy_doc_claim(conn, project_id=1, slug=DOC) is None
    finally:
        conn.close()


def test_item_owned_claim_refuses_the_itemless_lock(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seed_blitz_item(conn, 3104, 3104)
        _seed_session_claim(conn, 3104, WORKER)
        link_execution_document(
            conn,
            item_id=3104,
            project_id=1,
            slug=DOC,
            actor_id=1,
            session_id=WORKER,
        )
        acquire_strategy_doc_claim(
            conn,
            item_id=3104,
            session_id=WORKER,
            actor_id=1,
        )

        with pytest.raises(StrategyDocClaimConflictError):
            _lock(conn)
    finally:
        conn.close()


def test_terminal_blitz_leaves_the_document_lockable(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seeded_blitz(conn, 3105)
        conn.execute("UPDATE items SET status = 'done' WHERE id = %s", (3105,))
        conn.commit()

        claim = _lock(conn)
        assert claim["owner_session_id"] == COORDINATOR
    finally:
        conn.close()


def test_releasing_the_lock_hands_the_blitz_to_a_worker(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        _seed_doc(conn, DOC, "# Area plan\n")
        _seed_session(conn, COORDINATOR)
        _seed_session(conn, WORKER)
        _lock(conn)
        _seeded_blitz(conn, 3106)

        released = release_session_doc_claim(
            conn,
            project_id=1,
            slug=DOC,
            session_id=COORDINATOR,
            actor_id=1,
            reason="handing the plan to its Blitz",
        )
        assert released["release_mode"] == "normal"
        assert active_strategy_doc_claim(conn, project_id=1, slug=DOC) is None

        work_claim = claim_work(
            conn,
            session_id=WORKER,
            target=make_item_target(3106),
            reason="execute the Blitz",
        )
        assert work_claim["item_id"] == 3106
        document_claim = acquire_strategy_doc_claim(
            conn,
            item_id=3106,
            session_id=WORKER,
            actor_id=1,
        )
        assert document_claim["owner_kind"] == "item"
        assert document_claim["owner_item_id"] == 3106
    finally:
        conn.close()
