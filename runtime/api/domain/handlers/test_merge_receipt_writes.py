"""The registered merge-receipt write and read, against a real authority.

The merge boundary holds the checkout and reaches its control plane through
these two functions, so the wiring and the write have to be proven where the
row actually lands rather than at the client's call shape alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import item_merge_receipt_document as document
from yoke_core.domain import yoke_function_registry
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import merge_receipt_writes as writes

_MODULE = "yoke_core.domain.handlers.merge_receipt_writes"
BRANCH = "ITEM-1"
TARGET = "main"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-receipt"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _seed_item(db, item_id: int) -> None:
    conn = connect_test_db(db)
    try:
        insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
    finally:
        conn.close()


def test_the_write_lands_on_the_item_and_the_read_returns_it(db) -> None:
    item_id = 9601
    _seed_item(db, item_id)

    recorded = writes.handle_record_merge_receipt(
        _envelope(
            "merge_receipt.record",
            item_id=item_id,
            payload={
                "branch": BRANCH,
                "target": TARGET,
                "commit_sha": "a" * 40,
                "touched_files": ["feature.py"],
            },
        )
    )
    assert recorded.primary_success
    assert recorded.result_payload["entry"]["commit_sha"] == "a" * 40

    read = writes.handle_get_merge_receipt(
        _envelope(
            "merge_receipt.get",
            item_id=item_id,
            payload={"branch": BRANCH, "target": TARGET},
        )
    )
    assert read.primary_success
    assert read.result_payload["found"] is True
    assert read.result_payload["entry"]["touched_files"] == ["feature.py"]

    conn = connect_test_db(db)
    try:
        stored = document.find_entry(
            conn, item_id, branch=BRANCH, target=TARGET,
        )
    finally:
        conn.close()
    assert stored is not None and stored["commit_sha"] == "a" * 40


def test_a_second_write_folds_rather_than_replacing(db) -> None:
    item_id = 9602
    _seed_item(db, item_id)
    base = {"branch": BRANCH, "target": TARGET}

    writes.handle_record_merge_receipt(
        _envelope(
            "merge_receipt.record",
            item_id=item_id,
            payload={**base, "commit_sha": "a" * 40, "touched_files": ["x.py"]},
        )
    )
    outcome = writes.handle_record_merge_receipt(
        _envelope(
            "merge_receipt.record",
            item_id=item_id,
            payload={**base, "merge_sha": "b" * 40},
        )
    )

    entry = outcome.result_payload["entry"]
    assert entry["commit_sha"] == "a" * 40
    assert entry["merge_sha"] == "b" * 40
    assert entry["touched_files"] == ["x.py"]


def test_a_failure_is_stored_and_a_landing_settles_it(db) -> None:
    item_id = 9603
    _seed_item(db, item_id)
    base = {"branch": BRANCH, "target": TARGET}

    writes.handle_record_merge_receipt(
        _envelope(
            "merge_receipt.record",
            item_id=item_id,
            payload={
                **base,
                "failure": {
                    "label": "CI checks failed",
                    "phase": "pr-checks-poll",
                    "reason": "1 failing",
                },
            },
        )
    )
    conn = connect_test_db(db)
    try:
        assert document.current_failures(conn, [item_id])[item_id] == (
            "CI checks failed"
        )
    finally:
        conn.close()

    outcome = writes.handle_record_merge_receipt(
        _envelope(
            "merge_receipt.record",
            item_id=item_id,
            payload={**base, "merge_sha": "b" * 40},
        )
    )
    assert "failure" not in outcome.result_payload["entry"]


def test_a_missing_receipt_answers_not_found(db) -> None:
    item_id = 9604
    _seed_item(db, item_id)

    outcome = writes.handle_get_merge_receipt(
        _envelope(
            "merge_receipt.get", item_id=item_id, payload={"branch": BRANCH},
        )
    )

    assert outcome.primary_success
    assert outcome.result_payload["found"] is False
    assert outcome.result_payload["entry"] is None


def test_a_non_item_target_refuses_with_a_named_reason(db) -> None:
    outcome = writes.handle_record_merge_receipt(
        FunctionCallRequest(
            function="merge_receipt.record",
            actor=ActorContext(actor_id=None, session_id="s-merge-receipt"),
            target=TargetRef(kind="global"),
            payload={"branch": BRANCH, "target": TARGET},
        )
    )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "target_invalid"
    assert "item_id" in outcome.error.message


def test_a_payload_without_a_branch_refuses(db) -> None:
    outcome = writes.handle_record_merge_receipt(
        _envelope("merge_receipt.record", item_id=9605, payload={"target": TARGET})
    )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


class TestRegistration:
    @pytest.fixture(autouse=True)
    def reset_registry(self):
        yoke_function_registry.reset_registry_for_tests()
        yield
        yoke_function_registry.reset_registry_for_tests()

    @pytest.mark.parametrize(
        ("function_id", "side_effects"),
        (
            ("merge_receipt.record", ("item_merge_receipt_write",)),
            ("merge_receipt.get", ()),
        ),
    )
    def test_the_write_is_internal_session_optional_and_claim_free(
        self, function_id: str, side_effects: tuple[str, ...],
    ) -> None:
        init_register.register_all_handlers()
        entry = yoke_function_registry.lookup(function_id)

        assert entry is not None
        assert entry.adapter_status == "internal"
        assert entry.owner_module == _MODULE
        assert entry.target_kinds == ("item",)
        assert entry.side_effects == side_effects
        # The merge runs in a subprocess that may resolve no ambient session,
        # and the item claim is enforced upstream by the merge boundary.
        assert entry.ambient_session_required is False
        assert entry.claim_required_kind is None
