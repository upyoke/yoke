"""The host-turn wake's resume re-freezes a member execution moved by takeover."""

from __future__ import annotations

import json
from types import SimpleNamespace

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.test_deployment_qa_execution_refreeze import (
    _order,
    _queued_then_taken_over,
    _redeploy_new,
)
from yoke_core.domain.deployment_qa_execution_refreeze import resume_moved_execution
from yoke_core.domain.qa_plan_execution_reentry import PAUSE_REASON
from yoke_core.domain.qa_plan_execution_store import select_plan_execution


def _pause(conn, execution_id, phase):
    evidence = {"phase": phase, "cursor": 0, "request_id": "host-turn", "attempts": []}
    conn.execute(
        "UPDATE qa_plan_executions SET release_reason=%s WHERE id=%s",
        (PAUSE_REASON + json.dumps(evidence), execution_id),
    )
    conn.commit()


def _resume(conn, execution_id):
    execution = select_plan_execution(conn, execution_id, lock=False)
    return resume_moved_execution(
        conn,
        execution,
        SimpleNamespace(checkout_path=None, expected_branch=None, test_machine=None),
        SimpleNamespace(actor_id="1", session_id=takeover.DRIVER_SESSION),
    )


def test_resume_re_freezes_a_waiting_member_execution_in_place(test_db, monkeypatch):
    moved = _queued_then_taken_over(test_db, monkeypatch)
    _pause(test_db, moved["id"], "checkin")
    order = _order(test_db, moved["id"])
    _redeploy_new(test_db)

    # No `qa plan materialize` precedes a resume; the resume rebinds the cases.
    resumed = _resume(test_db, moved["id"])

    assert resumed is not None and resumed["id"] == moved["id"]
    assert resumed["state"] == "active"
    deployment = resumed["execution_target"]["deployment"]
    assert deployment["run_id"] == takeover.NEW
    assert deployment["release_lineage"] == takeover.NEW_LINEAGE
    assert deployment["starting_run_id"] == takeover.OLD
    assert _order(test_db, moved["id"]) == order
    reason = json.loads(resumed["release_reason"][len(PAUSE_REASON) :])
    assert reason["resumed"] is True


def test_resume_keeps_the_target_of_a_case_whose_outcome_is_unknown(
    test_db, monkeypatch
):
    moved = _queued_then_taken_over(test_db, monkeypatch)
    _pause(test_db, moved["id"], "case")
    _redeploy_new(test_db)

    assert _resume(test_db, moved["id"]) is None
    kept = select_plan_execution(test_db, moved["id"], lock=False)
    assert kept["execution_target_digest"] == moved["execution_target_digest"]
