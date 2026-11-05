"""Reviewed and terminated QA executions leave no capture run unsettled.

An agent verdict settles its capture in place. An aborted walk preserves a
typed review bundle for completed captures and still owes their judgment.
"""

from __future__ import annotations

from runtime.api.domain.qa_capture_settlement_test_support import (
    ACTOR as ACTOR,
    _capture_attempt as _capture_attempt,
    _materialize_mission as _materialize_mission,
    _request as _request,
    _submit_pass as _submit_pass,
    _unsettled_run_ids as _unsettled_run_ids,
)


from typing import Any

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import (
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_terminal_settlement import find_unsettled_records


def test_review_submission_settles_the_capture_run_in_place(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4601
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db,
        item_id=item_id,
        requirement_id=requirement_id,
    )
    execution = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, execution)
    assert bundle is not None
    capture_run_id = bundle["cases"][0]["capture_run_id"]
    assert _unsettled_run_ids(test_db, requirement_id) == [capture_run_id]

    result = _submit_pass(
        test_db,
        execution,
        bundle,
        requirement_id,
        "Ranked findings cover the expected outcome.",
    )

    assert result["state"] == "passed"
    assert _unsettled_run_ids(test_db, requirement_id) == []
    capture_row = test_db.execute(
        "SELECT verdict,verdict_reason,execution_status,case_outcome "
        "FROM qa_runs WHERE id=%s",
        (capture_run_id,),
    ).fetchone()
    assert capture_row["verdict"] == "pass"
    assert capture_row["verdict_reason"] == (
        "Ranked findings cover the expected outcome."
    )
    assert capture_row["execution_status"] == "captured"
    assert capture_row["case_outcome"] == "needs_review"

    # A replayed submission settles nothing new and unsettles nothing old.
    replay = _submit_pass(
        test_db,
        execution,
        bundle,
        requirement_id,
        "Ranked findings cover the expected outcome.",
    )
    assert replay["state"] == "passed"
    assert len(replay["verdicts"]) == 1
    assert _unsettled_run_ids(test_db, requirement_id) == []


def test_aborted_execution_preserves_its_capture_for_review(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4602
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db,
        item_id=item_id,
        requirement_id=requirement_id,
    )
    assert len(_unsettled_run_ids(test_db, requirement_id)) == 1

    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, execution_id),
        state="aborted",
        reason="operator aborted the stalled walk",
    )

    assert len(_unsettled_run_ids(test_db, requirement_id)) == 1
    settled = test_db.execute(
        "SELECT verdict,verdict_reason FROM qa_runs "
        "WHERE qa_requirement_id=%s AND performed_by='agent_mission'",
        (requirement_id,),
    ).fetchone()
    assert settled["verdict"] is None
    execution = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, execution, completed_captures_only=True)
    assert bundle is not None
    _submit_pass(
        test_db, execution, bundle, requirement_id, "Completed capture reviewed."
    )
    assert execution["state"] == "aborted"
    assert find_unsettled_records(test_db, item_id=item_id) == []


def test_gate_summary_and_terminal_gate_agree_after_review(
    test_db: Any,
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    item_id = 4604
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    execution_id = _capture_attempt(
        test_db,
        item_id=item_id,
        requirement_id=requirement_id,
    )
    execution = lock_plan_execution(test_db, execution_id)
    bundle = begin_plan_review(test_db, execution)
    _submit_pass(test_db, execution, bundle, requirement_id, "Findings complete.")

    pass_row = test_db.execute(
        "SELECT 1 FROM qa_runs r "
        "JOIN qa_requirements req ON req.id = r.qa_requirement_id "
        "WHERE req.item_id=%s AND r.verdict='pass' LIMIT 1",
        (item_id,),
    ).fetchone()
    assert pass_row is not None
    assert find_unsettled_records(test_db, item_id=item_id) == []
