import json

import pytest

from runtime.api.domain.qa_plan_execution_authority_test_support import _materialize_two_cases
from yoke_core.domain import qa_case_source_lane
from yoke_core.domain.handlers.qa_plan_command_record import PlanCommandRecordRequest, _record
from yoke_core.domain.qa_plan_execution_store import build_execution_roster
from yoke_core.domain.qa_walk_authority import _artifact_execution_id


def test_walk_lane_uses_the_requester_and_rejects_a_moved_commit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qa_case_source_lane, "resolve_source_lane",
        lambda conn, **kwargs: calls.append(kwargs) or {"lane_commit_sha": "b" * 40},
    )
    with pytest.raises(qa_case_source_lane.WalkLaneMoved, match="qa_lane_moved"):
        qa_case_source_lane.resolve_walk_lane(
            None, item_id=21, session_id="claim-holder", expected_branch="item-lane",
            expected_sha="a" * 40,
        )
    assert calls == [{"item_id": 21, "session_id": "claim-holder", "expected_branch": "item-lane"}]


def test_command_evidence_can_only_settle_its_own_frozen_revision_and_execution(test_db):
    item_id = 4571
    _materialize_two_cases(test_db, item_id=item_id)
    case = build_execution_roster(
        test_db, item_id=item_id, transition_id="implemented",
    )[0]
    sha = "a" * 40
    case["lane_commit_sha"] = sha
    execution = {"id": "delegated-host-command"}
    base = {
        "execution_id": execution["id"], "ordinal": 0,
        "requirement_id": case["requirement_id"], "duration_ms": 10,
    }

    def capture(commit, **overrides):
        return PlanCommandRecordRequest(
            **{**base, **overrides},
            raw_result=json.dumps({"verification_tree": {"head_sha": commit}}),
        )

    with pytest.raises(ValueError, match="qa_lane_moved"):
        _record(test_db, execution, case, capture("b" * 40))
    run_id = _record(test_db, execution, case, capture(sha))
    assert _artifact_execution_id(
        test_db, run_id=run_id, requirement_id=case["requirement_id"],
    ) == execution["id"]
    with pytest.raises(ValueError, match="qa_plan_command_run_mismatch"):
        _record(
            test_db, {"id": "unrelated-execution"}, case,
            capture(sha, run_id=run_id, verdict="pass"),
        )
    assert _record(test_db, execution, case, capture(sha, run_id=run_id, verdict="pass")) == run_id
    assert test_db.execute("SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)).fetchone()[0] == "pass"
