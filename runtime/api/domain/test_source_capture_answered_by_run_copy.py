"""An accepted run copy settles the item's own verdictless capture on its source.

A post-deploy source requirement can carry the item's own capture, recorded
``captured``/``needs_review`` with no verdict, while the completion run's copy
of the same case passes. The copy's acceptance is the source's settlement, so
the done gate and the gate summary both stop counting that capture; before the
copy is accepted, both name it.
"""

from __future__ import annotations

from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.domain.test_terminal_post_deploy_settlement import (
    _accept_member_qa,
    _source_member,
)
from runtime.api.fixtures.backlog import insert_qa_run
from yoke_core.domain.deployment_run_collective_finalization import mark_settling
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gate_summary import render_gate_summary
from yoke_core.domain.qa_gate_summary_text import _format_text
from yoke_core.domain.qa_terminal_settlement import (
    find_unsettled_records,
    terminal_transition_result,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _capture(conn, source_id: int) -> int:
    row = insert_qa_run(
        conn,
        qa_requirement_id=source_id,
        verdict=None,
        execution_status="captured",
        case_outcome="needs_review",
    )
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _summary(conn, item_id: int) -> dict:
    return render_gate_summary(
        GateTarget(item_id=item_id), str(conn.info.dsn), transition_name="implemented"
    )


def test_unaccepted_copy_leaves_the_capture_unsettled_in_gate_and_summary(test_db):
    item_id, _run_id, source_id = _source_member(
        test_db, workflow="dash", plan_source=False
    )
    capture_id = _capture(test_db, source_id)

    [record] = find_unsettled_records(test_db, item_id=item_id)
    assert (record.kind, record.record_id) == ("run", str(capture_id))
    refusal = terminal_transition_result(
        test_db, item_id, "done", load_item_workflow_runtime(test_db, item_id)
    )
    assert refusal and refusal["error_code"] == "GATE_QA_TERMINAL_SETTLEMENT"

    summary = _summary(test_db, item_id)
    assert summary["satisfied"] is False
    assert summary["unsettled_records"] == [
        {"kind": "run", "record_id": str(capture_id), "detail": record.detail}
    ]
    text = _format_text(summary)
    assert "Status: UNSATISFIED" in text
    assert f"    - run #{capture_id}: {record.detail}" in text


def test_accepted_copy_settles_the_capture_for_gate_and_summary(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    item_id, run_id, source_id = _source_member(
        test_db, workflow="dash", plan_source=False
    )
    _capture(test_db, source_id)
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    mark_settling(test_db, run_id)

    assert find_unsettled_records(test_db, item_id=item_id) == []
    assert (
        terminal_transition_result(
            test_db, item_id, "done", load_item_workflow_runtime(test_db, item_id)
        )
        is None
    )
    summary = _summary(test_db, item_id)
    assert summary["unsettled_records"] == []
    [source] = [row for row in summary["requirements"] if row["id"] == source_id]
    assert source["satisfied"] is True
