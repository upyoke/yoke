"""A single case respects the live custody of its own partition."""

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


def _begin_case(
    conn: Any, tmp_path: Any, requirement_id: int, *, session_id: str = SESSION
) -> dict[str, Any]:
    return begin_plan_execution(
        conn,
        item_id=ITEM_ID,
        transition_id=TRANSITION,
        requirement_id=requirement_id,
        checkout_path=str(tmp_path / BRANCH),
        expected_branch=BRANCH,
        actor_id="1",
        session_id=session_id,
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


def test_one_sessions_live_cursor_names_the_execution_and_its_resume(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids, live = _live_case(test_db, tmp_path, monkeypatch)
    before = _row(test_db, str(live["id"]))

    with pytest.raises(QaPlanExecutionStateError) as refusal:
        _begin_case(test_db, tmp_path, ids["receiving-mission"])
    test_db.rollback()

    message = str(refusal.value)
    assert message.startswith("qa_partition_unavailable:")
    assert str(live["id"]) in message
    assert f"yoke qa plan run --resume-execution-id {live['id']}" in message
    assert "target_env" not in message
    assert _row(test_db, str(live["id"])) == before


def test_disjoint_sessions_can_run_while_another_partition_awaits_review(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    ids, live = _live_case(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
        (str(live["id"]),),
    )
    test_db.commit()
    before = _row(test_db, str(live["id"]))

    # Only this storage-level fixture shares its source lane. Dispatcher tests
    # exercise the production launch grant for a second session.
    from yoke_core.domain import qa_case_source_lane as source
    actual_lanes = source.claimed_worktrees
    monkeypatch.setattr(
        source, "claimed_worktrees",
        lambda conn, *, session_id: actual_lanes(conn, session_id=SESSION),
    )
    with pytest.raises(QaPlanExecutionStateError, match=f"qa_partition_unavailable:.*{live['id']}"):
        _begin_case(test_db, tmp_path, ids["full-suite"], session_id="other-walker")
    test_db.rollback()
    disjoint = _begin_case(
        test_db, tmp_path, ids["receiving-mission"], session_id="other-walker",
    )
    assert [row["requirement_id"] for row in disjoint["roster"]] == [ids["receiving-mission"]]
    assert disjoint["session_id"] == "other-walker"
    assert _row(test_db, str(live["id"])) == before


def test_an_empty_roster_refuses_without_the_target_env_recovery() -> None:
    with pytest.raises(QaPlanExecutionStateError) as refusal:
        execution_target_for_roster([])

    message = str(refusal.value)
    assert message.startswith("qa_plan_roster_empty:")
    assert "target_env" not in message
