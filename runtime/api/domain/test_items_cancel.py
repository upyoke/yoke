"""Behavior of the first-class item cancel command.

Covers ``items.cancel.run``: it consumes ``execute_close``, takes the
claim like the flag verbs, cancels a frozen item in one step, and
refuses a foreign holder without touching that claim.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog_close_op, backlog_update_op
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.handlers.items_cancel import handle_cancel


SESSION = "cancel-verb-session"


@pytest.fixture(autouse=True)
def _isolate_write_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(backlog_update_op, "run_post_db_sync", lambda **_kwargs: 0)
    monkeypatch.setattr(
        backlog_close_op._rendering, "_post_comment", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        backlog_close_op._rendering, "_close_issue", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        backlog_close_op._rendering, "_maybe_rebuild_board", lambda *_a, **_k: None
    )


def _seed_session(conn: Any, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "workspace, offered_at, last_heartbeat) VALUES "
        "(%s, 'claude-code', 'anthropic', 'test', '/tmp', %s, %s) "
        "ON CONFLICT (session_id) DO NOTHING",
        (session_id, now, now),
    )
    conn.commit()


@pytest.fixture(autouse=True)
def _caller_session(test_db) -> None:
    _seed_session(test_db, SESSION)


def _live_claims(conn: Any, item_id: int) -> list:
    target = make_item_target(item_id)
    rows = conn.execute(
        "SELECT session_id FROM work_claims "
        "WHERE target_kind = %s AND scope = %s AND released_at IS NULL",
        (target.kind, target.scope_json()),
    ).fetchall()
    return [str(row["session_id"]) for row in rows]


def _request(item_id: int, **payload: Any) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.cancel.run",
        actor=ActorContext(actor_id="1", session_id=SESSION),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _row(conn: Any, item_id: int) -> tuple:
    row = conn.execute(
        "SELECT status, frozen, resolution, resolution_ref FROM items WHERE id = %s",
        (item_id,),
    ).fetchone()
    return (
        str(row["status"]),
        bool(row["frozen"]),
        row["resolution"],
        row["resolution_ref"],
    )


class TestCancel:
    def test_cancels_and_releases_an_acquired_claim(self, test_db) -> None:
        insert_item(test_db, id=8401, status="implementing")
        outcome = handle_cancel(_request(8401, reason="superseded by later work"))
        assert outcome.primary_success, outcome.error
        assert _row(test_db, 8401)[0:3] == (
            "cancelled",
            False,
            "superseded by later work",
        )
        assert outcome.result_payload["changed"] is True
        assert _live_claims(test_db, 8401) == []

    def test_cancels_a_frozen_item_without_a_thaw_flag(self, test_db) -> None:
        insert_item(test_db, id=8402, status="implementing", frozen=1)
        outcome = handle_cancel(_request(8402, reason="will never resume"))
        assert outcome.primary_success, outcome.error
        status, frozen, resolution, _ref = _row(test_db, 8402)
        assert (status, frozen, resolution) == (
            "cancelled",
            False,
            "will never resume",
        )
        assert outcome.result_payload["frozen_cleared"] is True

    def test_records_the_superseding_item(self, test_db) -> None:
        insert_item(test_db, id=8403, status="idea")
        insert_item(test_db, id=8404, status="implementing")
        outcome = handle_cancel(_request(8403, reason="superseded", ref="YOK-8404"))
        assert outcome.primary_success, outcome.error
        _status, _frozen, _resolution, ref = _row(test_db, 8403)
        assert ref
        assert "8404" in str(ref)

    def test_empty_reason_is_invalid(self, test_db) -> None:
        insert_item(test_db, id=8405, status="idea")
        outcome = handle_cancel(_request(8405, reason="   "))
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"
        assert _row(test_db, 8405)[0] == "idea"

    def test_cancel_releases_a_claim_the_caller_held(self, test_db) -> None:
        insert_item(test_db, id=8406, status="implementing")
        claim_work(
            test_db,
            session_id=SESSION,
            target=make_item_target(8406),
            reason="already working",
        )
        test_db.commit()
        outcome = handle_cancel(_request(8406, reason="dropped"))
        assert outcome.primary_success, outcome.error
        assert _live_claims(test_db, 8406) == []

    def test_a_foreign_holder_refuses_the_write(self, test_db) -> None:
        insert_item(test_db, id=8407, status="implementing")
        _seed_session(test_db, "someone-else")
        claim_work(
            test_db,
            session_id="someone-else",
            target=make_item_target(8407),
            reason="mid-flight",
        )
        test_db.commit()
        outcome = handle_cancel(_request(8407, reason="dropped"))
        assert not outcome.primary_success
        assert outcome.error.code == "claim_held"
        assert "someone-else" in outcome.error.message
        assert _row(test_db, 8407)[0] == "implementing"
        assert _live_claims(test_db, 8407) == ["someone-else"]

    def test_unknown_item_is_not_found(self, test_db) -> None:
        del test_db
        outcome = handle_cancel(_request(999_888, reason="gone"))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"
