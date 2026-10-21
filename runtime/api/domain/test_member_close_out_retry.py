"""A refused member close-out retries when the record blocking it settles.

The member's item QA is accepted on its executing run, but its own capture
has no verdict, so the done write refuses. The refusal notice names that
record. Settling it — a verdict through its ordinary write, or a waiver
through the follow-up it owes the background replay — re-runs the same
close-out, and the member reaches done without a re-drive.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog import insert_qa_requirement, insert_qa_run
from yoke_core.domain.deployment_member_close_out_retry import (
    after_record_settled,
    retry_member_close_out,
)
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
)
from yoke_core.domain.qa_requirement_ops import waive_requirement
from yoke_core.domain.qa_settlement_followups import replay_settlement_followups
from yoke_core.domain.qa_run_execution_evidence import commit_settled_verdict
from yoke_core.domain.qa_run_verdict_record import update_qa_run

RUN_ID = "run-close-out-retry"


def _row_id(row: Any) -> int:
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _blocked_member(conn: Any) -> tuple[int, int]:
    """MEMBER_A's QA is accepted, but its own capture still owes a verdict."""
    _seed_final_run(conn, RUN_ID, shared_qa=False)
    requirement_id = _row_id(
        insert_qa_requirement(conn, item_id=MEMBER_A, blocking_mode="non_blocking")
    )
    capture_id = _row_id(
        insert_qa_run(
            conn,
            qa_requirement_id=requirement_id,
            verdict=None,
            execution_status="captured",
        )
    )
    conn.commit()
    _settle(conn, run_id=RUN_ID, stage="item-qa", member=MEMBER_A)
    return requirement_id, capture_id


def _refusal_bodies(conn: Any, item_id: int) -> list[str]:
    key = item_qa_accepted_idempotency_key(item_id, RUN_ID) + ":refused-%"
    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s ORDER BY 1",
        (key,),
    ).fetchall()
    return [row["body"] for row in rows]


def test_the_refusal_notice_names_the_blocking_record(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _requirement_id, capture_id = _blocked_member(test_db)

    assert _status(test_db, MEMBER_A) == "release"
    [body] = _refusal_bodies(test_db, MEMBER_A)
    assert "Automatic close-out failed" in body
    assert f"  - run #{capture_id}:" in body


@pytest.mark.parametrize("settle", ["verdict", "waiver"])
def test_settling_the_blocker_closes_the_member(test_db, monkeypatch, settle) -> None:
    _isolate_status_effects(monkeypatch)
    requirement_id, capture_id = _blocked_member(test_db)

    if settle == "verdict":
        update_qa_run(test_db, capture_id, {"verdict": "pass", "verdict_reason": "ok"})
        commit_settled_verdict(test_db, capture_id)
    else:
        waive_requirement(test_db, requirement_id, "not needed here", force=True)
        # The waive answers before the close-out; the queue worker runs it.
        assert _status(test_db, MEMBER_A) == "release"
        assert replay_settlement_followups(test_db)["replayed"] == [MEMBER_A]

    assert _status(test_db, MEMBER_A) == "done"
    assert _status(test_db, MEMBER_B) == "release"


def test_a_member_its_run_has_not_accepted_is_left_to_its_stage(
    test_db, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _blocked_member(test_db)

    assert retry_member_close_out(test_db, item_id=MEMBER_B) == []
    after_record_settled(test_db, item_id=MEMBER_B)
    assert _status(test_db, MEMBER_B) == "release"
    assert _refusal_bodies(test_db, MEMBER_B) == []
