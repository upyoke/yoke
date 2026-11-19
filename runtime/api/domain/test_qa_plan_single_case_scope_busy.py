"""A single case on a busy item transition names the live execution that blocks it."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_qa_plan_item_target_partition import (
    BRANCH,
    ITEM_ID,
    SESSION,
    TRANSITION,
    _mixed_roster,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    execution_target_for_roster,
)


def _begin_case(conn: Any, tmp_path: Any, requirement_id: int) -> dict[str, Any]:
    return begin_plan_execution(
        conn,
        item_id=ITEM_ID,
        transition_id=TRANSITION,
        requirement_id=requirement_id,
        checkout_path=str(tmp_path / BRANCH),
        expected_branch=BRANCH,
        actor_id="1",
        session_id=SESSION,
    )


def _row(conn: Any, execution_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM qa_plan_executions WHERE id=%s", (execution_id,)
    ).fetchone()
    conn.rollback()
    return dict(row)


def _live_case(conn: Any, tmp_path: Any, monkeypatch: Any) -> tuple[dict, dict]:
    ids = _mixed_roster(conn, tmp_path, monkeypatch)
    live = _begin_case(conn, tmp_path, ids["full-suite"])
    return ids, live


def test_another_case_refuses_naming_the_live_execution_and_its_resume(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids, live = _live_case(test_db, tmp_path, monkeypatch)
    before = _row(test_db, str(live["id"]))

    with pytest.raises(QaPlanExecutionStateError) as refusal:
        _begin_case(test_db, tmp_path, ids["receiving-mission"])
    test_db.rollback()

    message = str(refusal.value)
    assert message.startswith("qa_single_case_scope_busy:")
    assert str(live["id"]) in message
    assert f"requirement {ids['full-suite']}" in message
    assert f"yoke qa case run --requirement-id {ids['full-suite']}" in message
    assert f"yoke qa plan abort --execution-id {live['id']}" in message
    assert "target_env" not in message
    assert _row(test_db, str(live["id"])) == before


def test_a_live_execution_awaiting_review_names_the_review_command(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids, live = _live_case(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
        (str(live["id"]),),
    )
    test_db.commit()
    before = _row(test_db, str(live["id"]))

    with pytest.raises(QaPlanExecutionStateError) as refusal:
        _begin_case(test_db, tmp_path, ids["receiving-mission"])
    test_db.rollback()

    message = str(refusal.value)
    assert message.startswith("qa_single_case_scope_busy:")
    assert "(awaiting_walk_review)" in message
    assert "yoke qa plan review-begin --item " in message
    assert f"--execution-id {live['id']}" in message
    assert "review-submit" in message
    assert _row(test_db, str(live["id"])) == before


def test_an_empty_roster_refuses_without_the_target_env_recovery() -> None:
    with pytest.raises(QaPlanExecutionStateError) as refusal:
        execution_target_for_roster([])

    message = str(refusal.value)
    assert message.startswith("qa_plan_roster_empty:")
    assert "target_env" not in message
