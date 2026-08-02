"""In-process coverage for the operator merge-timestamp repair handler.

The handler is a thin dispatcher wrapper over
``item_merge_provenance_operator.operator_correct_merged_at``; the guardrail
matrix itself is covered by ``test_item_merge_provenance_operator``. These
tests prove the wrapper writes a real DB row server-side, maps each refusal
class onto its declared error code, and returns the declared response shape.
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
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import item_merge_provenance as writes

FUNCTION = "items.merge_provenance.operator_correct"
LANDED_AT = "2026-08-01T18:42:00Z"
REASON = "branch landed via gh pr merge; PR merge path unavailable"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        monkeypatch.delenv("YOKE_HOOK_EVENT", raising=False)
        yield db_path


def _seed(db, item_id: int, *, status: str = "done") -> None:
    conn = connect_test_db(db)
    try:
        insert_item(
            conn,
            id=item_id,
            workflow_id="dash",
            status=status,
            source=str(seed_human_actor(conn)),
        )
    finally:
        conn.close()


def _merged_at(db, item_id: int) -> str:
    conn = connect_test_db(db)
    try:
        row = conn.execute(
            "SELECT merged_at FROM items WHERE id = %s", (item_id,)
        ).fetchone()
    finally:
        conn.close()
    value = row["merged_at"] if hasattr(row, "keys") else row[0]
    return str(value or "")


def _envelope(*, item_id=None, payload=None):
    return FunctionCallRequest(
        function=FUNCTION,
        actor=ActorContext(actor_id=None, session_id="s-merge-provenance"),
        target=(
            TargetRef(kind="item", item_id=item_id)
            if item_id is not None
            else TargetRef(kind="global")
        ),
        payload=payload or {},
    )


def test_writes_merged_at_and_returns_declared_shape(db):
    item_id = 9611
    _seed(db, item_id)

    outcome = writes.handle_operator_correct_merged_at(
        _envelope(
            item_id=item_id,
            payload={"merged_at": LANDED_AT, "operator_reason": REASON},
        )
    )

    assert outcome.primary_success, outcome.error
    writes.OperatorCorrectMergedAtResponse(**outcome.result_payload)
    assert outcome.result_payload["merged_at"] == LANDED_AT
    assert _merged_at(db, item_id) == LANDED_AT


def test_missing_operator_reason_is_payload_invalid(db):
    outcome = writes.handle_operator_correct_merged_at(
        _envelope(item_id=9612, payload={"merged_at": LANDED_AT})
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"


def test_missing_item_target_is_invalid(db):
    outcome = writes.handle_operator_correct_merged_at(
        _envelope(payload={"merged_at": LANDED_AT, "operator_reason": REASON})
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "target_invalid"


def test_non_terminal_item_is_a_refusal_not_a_failure(db):
    item_id = 9613
    _seed(db, item_id, status="implementing")

    outcome = writes.handle_operator_correct_merged_at(
        _envelope(
            item_id=item_id,
            payload={"merged_at": LANDED_AT, "operator_reason": REASON},
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "merged_at_correction_refused"
    assert _merged_at(db, item_id) == ""


def test_hook_context_has_its_own_error_code(db, monkeypatch):
    item_id = 9614
    _seed(db, item_id)
    monkeypatch.setenv("YOKE_HOOK_EVENT", "PreToolUse")

    outcome = writes.handle_operator_correct_merged_at(
        _envelope(
            item_id=item_id,
            payload={"merged_at": LANDED_AT, "operator_reason": REASON},
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "hook_context_refused"
    assert _merged_at(db, item_id) == ""
