"""Concurrency and rollback proofs for strategy-document claim lifecycle."""

from __future__ import annotations

import threading
from typing import Any, Callable

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    seed_blitz_item,
    seed_session_claim,
    seed_strategy_doc,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain import strategy_execution_claim_lifecycle
from yoke_core.domain.item_terminal_resources import (
    release_for_terminal_transition,
)
from yoke_core.domain.strategy_execution import (
    StrategyExecutionLinkError,
    acquire_strategy_doc_claim,
    active_strategy_doc_claim,
    link_execution_document,
    release_strategy_doc_claim,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


ITEM_ID = 2081
SESSION_ID = "strategy-claim-atomicity"
OLD_SLUG = "ATOMIC-OLD"
NEW_SLUG = "ATOMIC-NEW"


def _connections(test_db, count: int) -> tuple[Any, ...]:
    name = str(test_db.info.dbname)
    return tuple(connect_test_database(name) for _ in range(count))


def _join(thread: threading.Thread) -> None:
    thread.join(timeout=10)
    assert not thread.is_alive(), f"thread {thread.name} did not finish"


def _seed_linked_item(test_db) -> None:
    seed_strategy_doc(test_db, OLD_SLUG, "# Original execution plan\n")
    seed_strategy_doc(test_db, NEW_SLUG, "# Replacement execution plan\n")
    seed_blitz_item(test_db, ITEM_ID, ITEM_ID)
    seed_session_claim(test_db, ITEM_ID, SESSION_ID)
    link_execution_document(
        test_db,
        item_id=ITEM_ID,
        project_id=1,
        slug=OLD_SLUG,
        actor_id=1,
        session_id=SESSION_ID,
    )


def _capture(
    outcomes: dict[str, object],
    name: str,
    operation: Callable[[], object],
    started: threading.Event,
    done: threading.Event,
) -> None:
    started.set()
    try:
        outcomes[name] = operation()
    except BaseException as exc:  # noqa: BLE001 - thread outcome evidence
        outcomes[name] = exc
    finally:
        done.set()


def test_claim_acquisition_serializes_relink_and_keeps_document_consistent(
    test_db,
) -> None:
    _seed_linked_item(test_db)
    gate_conn, acquire_conn, link_conn = _connections(test_db, 3)
    acquire_started = threading.Event()
    acquire_done = threading.Event()
    link_started = threading.Event()
    link_done = threading.Event()
    outcomes: dict[str, object] = {}
    threads: list[threading.Thread] = []

    try:
        lock_item_workflow_bindings(gate_conn, (ITEM_ID,))
        threads = [
            threading.Thread(
                target=_capture,
                args=(
                    outcomes,
                    "acquire",
                    lambda: acquire_strategy_doc_claim(
                        acquire_conn,
                        item_id=ITEM_ID,
                        session_id=SESSION_ID,
                        actor_id=1,
                    ),
                    acquire_started,
                    acquire_done,
                ),
                name="strategy-claim-acquirer",
            ),
            threading.Thread(
                target=_capture,
                args=(
                    outcomes,
                    "link",
                    lambda: link_execution_document(
                        link_conn,
                        item_id=ITEM_ID,
                        project_id=1,
                        slug=NEW_SLUG,
                        actor_id=1,
                        session_id=SESSION_ID,
                    ),
                    link_started,
                    link_done,
                ),
                name="strategy-document-relinker",
            ),
        ]
        threads[0].start()
        assert acquire_started.wait(timeout=10)
        assert not acquire_done.wait(timeout=0.2)
        threads[1].start()
        assert link_started.wait(timeout=10)
        assert not link_done.wait(timeout=0.2)
        gate_conn.commit()
        for thread in threads:
            _join(thread)
    finally:
        gate_conn.rollback()
        for thread in threads:
            if thread.is_alive():
                _join(thread)
        gate_conn.close()
        acquire_conn.close()
        link_conn.close()

    assert isinstance(outcomes["acquire"], dict)
    assert isinstance(outcomes["link"], StrategyExecutionLinkError)
    link = test_db.execute(
        "SELECT strategy_doc_slug FROM item_strategy_docs WHERE item_id=%s",
        (ITEM_ID,),
    ).fetchone()
    claim = active_strategy_doc_claim(test_db, item_id=ITEM_ID)
    assert str(link[0]) == OLD_SLUG
    assert claim is not None
    assert str(claim["strategy_doc_slug"]) == OLD_SLUG


def test_concurrent_releases_report_exactly_one_success(test_db) -> None:
    _seed_linked_item(test_db)
    acquire_strategy_doc_claim(
        test_db,
        item_id=ITEM_ID,
        session_id=SESSION_ID,
        actor_id=1,
    )
    gate_conn, first_conn, second_conn = _connections(test_db, 3)
    first_started = threading.Event()
    first_done = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    outcomes: dict[str, object] = {}
    threads: list[threading.Thread] = []

    def release(conn: Any, reason: str) -> dict[str, Any]:
        return release_strategy_doc_claim(
            conn,
            item_id=ITEM_ID,
            session_id=SESSION_ID,
            actor_id=1,
            reason=reason,
        )

    try:
        lock_item_workflow_bindings(gate_conn, (ITEM_ID,))
        threads = [
            threading.Thread(
                target=_capture,
                args=(
                    outcomes,
                    "first",
                    lambda: release(first_conn, "first concurrent release"),
                    first_started,
                    first_done,
                ),
                name="strategy-claim-release-first",
            ),
            threading.Thread(
                target=_capture,
                args=(
                    outcomes,
                    "second",
                    lambda: release(second_conn, "second concurrent release"),
                    second_started,
                    second_done,
                ),
                name="strategy-claim-release-second",
            ),
        ]
        threads[0].start()
        assert first_started.wait(timeout=10)
        assert not first_done.wait(timeout=0.2)
        threads[1].start()
        assert second_started.wait(timeout=10)
        assert not second_done.wait(timeout=0.2)
        gate_conn.commit()
        for thread in threads:
            _join(thread)
    finally:
        gate_conn.rollback()
        for thread in threads:
            if thread.is_alive():
                _join(thread)
        gate_conn.close()
        first_conn.close()
        second_conn.close()

    successes = [value for value in outcomes.values() if isinstance(value, dict)]
    failures = [
        value for value in outcomes.values() if isinstance(value, BaseException)
    ]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], StrategyExecutionLinkError)
    assert active_strategy_doc_claim(test_db, item_id=ITEM_ID) is None


def test_stale_release_snapshot_cannot_report_success(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_linked_item(test_db)
    stale_claim = acquire_strategy_doc_claim(
        test_db,
        item_id=ITEM_ID,
        session_id=SESSION_ID,
        actor_id=1,
    )
    release_strategy_doc_claim(
        test_db,
        item_id=ITEM_ID,
        session_id=SESSION_ID,
        actor_id=1,
        reason="initial release",
    )
    monkeypatch.setattr(
        strategy_execution_claim_lifecycle,
        "active_strategy_doc_claim",
        lambda *_args, **_kwargs: stale_claim,
    )

    with pytest.raises(StrategyExecutionLinkError, match="no longer active"):
        release_strategy_doc_claim(
            test_db,
            item_id=ITEM_ID,
            session_id=SESSION_ID,
            actor_id=1,
            reason="stale retry",
        )


def test_terminal_cleanup_strategy_claim_rolls_back_with_status(test_db) -> None:
    _seed_linked_item(test_db)
    acquire_strategy_doc_claim(
        test_db,
        item_id=ITEM_ID,
        session_id=SESSION_ID,
        actor_id=1,
    )
    (transition_conn,) = _connections(test_db, 1)
    try:
        lock_item_workflow_bindings(transition_conn, (ITEM_ID,))
        transition_conn.execute(
            "UPDATE items SET status='cancelled' WHERE id=%s",
            (ITEM_ID,),
        )
        receipt = release_for_terminal_transition(
            transition_conn,
            item_id=ITEM_ID,
            target_status="cancelled",
            session_id=SESSION_ID,
            actor_id=1,
        )
        assert receipt.document_claim_released is True
        assert (
            active_strategy_doc_claim(
                transition_conn,
                item_id=ITEM_ID,
            )
            is None
        )
        transition_conn.rollback()
    finally:
        transition_conn.close()

    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (ITEM_ID,),
    ).fetchone()
    work_claim = test_db.execute(
        "SELECT released_at FROM work_claims WHERE item_id=%s AND session_id=%s",
        (ITEM_ID, SESSION_ID),
    ).fetchone()
    restored_claim = active_strategy_doc_claim(test_db, item_id=ITEM_ID)
    assert str(status[0]) == "implementing"
    assert work_claim[0] is None
    assert restored_claim is not None
    assert str(restored_claim["strategy_doc_slug"]) == OLD_SLUG
