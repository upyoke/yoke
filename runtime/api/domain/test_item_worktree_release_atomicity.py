"""Stale-validation proof for public item-worktree release."""

from __future__ import annotations

from contextlib import nullcontext
import threading
from typing import Any

from runtime.api.domain.handlers.test_item_worktree_handlers import _request
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import item_worktrees as handlers
from yoke_core.domain.item_worktrees import (
    LANE_IMPLEMENTATION,
    list_item_worktrees,
    record_released_item_worktree_history,
    record_item_worktree,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def test_release_revalidates_attestation_after_lane_refresh(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9631
    insert_item(
        test_db,
        id=item_id,
        workflow_id="issue",
        status="implemented",
    )
    original = record_item_worktree(
        test_db,
        item_id=item_id,
        branch="YOK-9631-old",
        path="/tmp/yoke-9631-old",
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()
    name = str(test_db.info.dbname)
    refresh_conn = connect_test_database(name)
    handler_conn = connect_test_database(name)
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: nullcontext(handler_conn),
    )
    handler_started = threading.Event()
    handler_done = threading.Event()
    outcomes: dict[str, Any] = {}
    request = _request(
        "item_worktrees.release",
        item_id=item_id,
        payload={
            "all_active": True,
            "reason": "evidence-only-recovery",
            "clean_lane_attestation": {
                "worktree_id": original["id"],
                "branch": original["branch"],
                "path": original["path"],
                "observed_clean": True,
            },
        },
    )

    def release_attested_lane() -> None:
        handler_started.set()
        try:
            outcomes["handler"] = handlers.handle_release(request)
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["handler"] = exc
        finally:
            handler_done.set()

    worker = threading.Thread(
        target=release_attested_lane,
        name="attested-lane-release",
    )
    try:
        lock_item_workflow_bindings(refresh_conn, (item_id,))
        worker.start()
        assert handler_started.wait(timeout=10)
        assert not handler_done.wait(timeout=0.2)
        refreshed = record_item_worktree(
            refresh_conn,
            item_id=item_id,
            branch="YOK-9631-refreshed",
            path="/tmp/yoke-9631-refreshed",
            lane_role=LANE_IMPLEMENTATION,
        )
        refresh_conn.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
    except BaseException:
        refresh_conn.rollback()
        worker.join(timeout=10)
        raise
    finally:
        refresh_conn.close()
        handler_conn.close()

    outcome = outcomes["handler"]
    assert not isinstance(outcome, BaseException)
    assert outcome.primary_success is False
    assert outcome.error.code == "clean_lane_attestation_stale"
    active = list_item_worktrees(test_db, item_id, active_only=True)
    assert [row["id"] for row in active] == [refreshed["id"]]


def test_terminal_history_insert_never_creates_active_lane(test_db) -> None:
    item_id = 9632
    insert_item(test_db, id=item_id, status="done")

    history = record_released_item_worktree_history(
        test_db,
        item_id=item_id,
        branch="YOK-9632-history",
        path="/tmp/yoke-9632-history",
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()

    assert history["state"] == "released"
    assert history["released_at"] is not None
    assert list_item_worktrees(test_db, item_id, active_only=True) == []
