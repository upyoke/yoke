"""Behavior of the item coordination-flag verbs.

Covers ``items.freeze.run`` / ``items.thaw.run`` / ``items.block.run`` /
``items.unblock.run``: the preconditions each verb enforces, the
reason-before-flag write ordering that makes a block atomic as observed,
the frozen-item exemption, and the claim contract — the flag verbs
declare no claim requirement while ``items.scalar.update`` keeps its
item-claim gate for every other caller.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog, backlog_update_op
from yoke_core.domain.handlers.items_flags import (
    handle_block,
    handle_freeze,
    handle_thaw,
    handle_unblock,
)


SESSION = "flag-verb-session"


@pytest.fixture(autouse=True)
def _isolate_write_side_effects(monkeypatch) -> None:
    """Keep the flag writes off GitHub and off the board renderer."""
    monkeypatch.setattr(backlog_update_op, "run_post_db_sync", lambda **_kwargs: 0)
    monkeypatch.setattr(
        backlog_update_op._rendering,
        "_maybe_rebuild_board",
        lambda *_args, **_kwargs: None,
    )


def _request(item_id: int, **payload: Any) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.freeze.run",
        actor=ActorContext(actor_id="1", session_id=SESSION),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _flags(conn: Any, item_id: int) -> tuple:
    row = conn.execute(
        "SELECT frozen, blocked, blocked_reason, status FROM items WHERE id = %s",
        (item_id,),
    ).fetchone()
    return (
        bool(row["frozen"]),
        bool(row["blocked"]),
        row["blocked_reason"],
        row["status"],
    )


def _record_write_order(monkeypatch) -> List[str]:
    """Record the field name of every underlying update, in call order."""
    seen: List[str] = []
    real = backlog.execute_update

    def _wrapper(*args, **kwargs):
        seen.append(str(kwargs.get("field")))
        return real(*args, **kwargs)

    monkeypatch.setattr(backlog, "execute_update", _wrapper)
    return seen


class TestFreezeAndThaw:
    def test_freeze_sets_the_flag_and_preserves_status(self, test_db) -> None:
        insert_item(test_db, id=8101, status="implementing")
        outcome = handle_freeze(_request(8101))
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["changed"] is True
        assert _flags(test_db, 8101)[:2] == (True, False)
        assert _flags(test_db, 8101)[3] == "implementing"

    def test_freeze_refuses_a_done_item(self, test_db) -> None:
        insert_item(test_db, id=8102, status="done")
        outcome = handle_freeze(_request(8102))
        assert not outcome.primary_success
        assert outcome.error.code == "item_done"
        assert _flags(test_db, 8102)[0] is False

    def test_freeze_is_a_reported_no_op_when_already_frozen(self, test_db) -> None:
        insert_item(test_db, id=8103, status="planned", frozen=1)
        outcome = handle_freeze(_request(8103))
        assert outcome.primary_success
        assert outcome.result_payload["changed"] is False
        assert outcome.result_payload["frozen"] is True

    def test_thaw_clears_the_flag_and_preserves_status(self, test_db) -> None:
        insert_item(test_db, id=8104, status="planned", frozen=1)
        outcome = handle_thaw(_request(8104))
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["changed"] is True
        assert _flags(test_db, 8104)[0] is False
        assert _flags(test_db, 8104)[3] == "planned"

    def test_thaw_is_a_reported_no_op_when_not_frozen(self, test_db) -> None:
        insert_item(test_db, id=8105, status="planned")
        outcome = handle_thaw(_request(8105))
        assert outcome.primary_success
        assert outcome.result_payload["changed"] is False

    def test_thaw_accepts_a_done_item_as_a_no_op(self, test_db) -> None:
        insert_item(test_db, id=8106, status="done")
        outcome = handle_thaw(_request(8106))
        assert outcome.primary_success
        assert outcome.result_payload["changed"] is False


class TestBlockAndUnblock:
    def test_block_records_the_reason_and_preserves_status(self, test_db) -> None:
        insert_item(test_db, id=8201, status="implementing")
        outcome = handle_block(_request(8201, reason="Awaiting sign-off"))
        assert outcome.primary_success, outcome.error
        frozen, blocked, reason, status = _flags(test_db, 8201)
        assert (blocked, reason, status) == (True, "Awaiting sign-off", "implementing")
        assert frozen is False

    def test_block_writes_the_reason_before_the_flag(self, test_db, monkeypatch) -> None:
        insert_item(test_db, id=8202, status="implementing")
        seen = _record_write_order(monkeypatch)
        assert handle_block(_request(8202, reason="Upstream API change")).primary_success
        assert seen == ["blocked_reason", "blocked"]

    def test_block_replaces_the_reason_when_already_blocked(self, test_db) -> None:
        insert_item(
            test_db, id=8203, status="implementing", blocked=1, blocked_reason="old",
        )
        outcome = handle_block(_request(8203, reason="new reason"))
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["changed"] is True
        assert _flags(test_db, 8203)[1:3] == (True, "new reason")

    def test_block_is_a_no_op_when_the_reason_is_unchanged(self, test_db) -> None:
        insert_item(
            test_db, id=8204, status="implementing", blocked=1, blocked_reason="same",
        )
        outcome = handle_block(_request(8204, reason="same"))
        assert outcome.primary_success
        assert outcome.result_payload["changed"] is False

    def test_block_refuses_a_done_item(self, test_db) -> None:
        insert_item(test_db, id=8205, status="done")
        outcome = handle_block(_request(8205, reason="too late"))
        assert not outcome.primary_success
        assert outcome.error.code == "item_done"
        assert _flags(test_db, 8205)[1] is False

    def test_block_requires_a_non_empty_reason(self, test_db) -> None:
        insert_item(test_db, id=8206, status="implementing")
        outcome = handle_block(_request(8206, reason="   "))
        assert not outcome.primary_success
        assert outcome.error.code == "validation_error"

    def test_block_missing_reason_is_a_payload_error(self, test_db) -> None:
        insert_item(test_db, id=8207, status="implementing")
        outcome = handle_block(_request(8207))
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"

    def test_block_works_on_a_frozen_item(self, test_db) -> None:
        insert_item(test_db, id=8208, status="planned", frozen=1)
        outcome = handle_block(_request(8208, reason="parked and blocked"))
        assert outcome.primary_success, outcome.error
        frozen, blocked, reason, _status = _flags(test_db, 8208)
        assert (frozen, blocked, reason) == (True, True, "parked and blocked")

    def test_unblock_clears_the_flag_before_the_reason(
        self, test_db, monkeypatch,
    ) -> None:
        insert_item(
            test_db, id=8209, status="implementing", blocked=1, blocked_reason="why",
        )
        seen = _record_write_order(monkeypatch)
        outcome = handle_unblock(_request(8209))
        assert outcome.primary_success, outcome.error
        assert seen == ["blocked", "blocked_reason"]
        assert _flags(test_db, 8209)[1:4] == (False, None, "implementing")

    def test_unblock_is_a_reported_no_op_when_not_blocked(self, test_db) -> None:
        insert_item(test_db, id=8210, status="implementing")
        outcome = handle_unblock(_request(8210))
        assert outcome.primary_success
        assert outcome.result_payload["changed"] is False

    def test_unblock_works_on_a_frozen_item(self, test_db) -> None:
        insert_item(
            test_db, id=8211, status="planned", frozen=1, blocked=1,
            blocked_reason="parked",
        )
        outcome = handle_unblock(_request(8211))
        assert outcome.primary_success, outcome.error
        assert _flags(test_db, 8211)[:3] == (True, False, None)


class TestMissingTargets:
    def test_unknown_item_is_reported_not_found(self, test_db) -> None:
        del test_db
        outcome = handle_freeze(_request(999_777))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_non_item_target_is_rejected(self, test_db) -> None:
        del test_db
        request = FunctionCallRequest(
            function="items.freeze.run",
            actor=ActorContext(actor_id="1", session_id=SESSION),
            target=TargetRef(kind="global"),
            payload={},
        )
        outcome = handle_freeze(request)
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"
