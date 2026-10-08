"""Terminal QA diagnostics for verdicts that need operator review."""

from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues

import json
import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.qa_terminal_settlement import (
    _blocking_requirement_rows,
    find_unsettled_records,
)
from yoke_core.domain.qa_browser_freshness_check import _latest_browser_run
from yoke_core.domain.qa_merging_identity import _passing_blocking_heads


@pytest.mark.parametrize("latest_verdict", [None, "pass", "fail"])
def test_settlement_counts_only_latest_execution(test_db, latest_verdict):
    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict=None)
    latest = insert_qa_run(
        test_db, qa_requirement_id=requirement["id"], verdict=latest_verdict
    )
    records = find_unsettled_records(test_db, item_id=item["id"])
    assert [record.record_id for record in records] == (
        [str(latest["id"])] if latest_verdict is None else []
    )


def test_detached_review_does_not_mask_latest_capture_identity(test_db):
    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(
        test_db, item_id=item["id"], method_id="browser-inspection"
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="browser_substrate",
        verdict=None,
    )
    sha = "b" * 40
    capture = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="browser_substrate",
        verdict="pass",
        completed_at="2026-01-01T00:00:01Z",
        raw_result=json.dumps({"code_identity": {"sha": sha}}),
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="agent",
        verdict="pass",
        raw_result="{}",
    )
    assert find_unsettled_records(test_db, item_id=item["id"]) == []
    rows = _blocking_requirement_rows(test_db, item["id"])
    assert rows[0]["run_id"] == capture["id"]
    assert rows[0]["recorded_head_sha"] == sha
    assert _passing_blocking_heads(test_db, item["id"]) == [sha]
    assert (
        blocking_requirement_issues(
            rows, accepted_shas=(sha,), public_ref="example", require_any=True
        )
        == []
    )
    assert _latest_browser_run(test_db, requirement["id"])["id"] == capture["id"]


def test_new_pending_capture_replaces_old_passing_capture(test_db):
    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="browser_substrate",
        verdict="pass",
    )
    latest = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="browser_substrate",
        verdict=None,
    )
    assert find_unsettled_records(test_db, item_id=item["id"])[0].record_id == str(
        latest["id"]
    )
    assert _latest_browser_run(test_db, requirement["id"]) is None


def test_undetermined_requirement_issue_preserves_reason():
    issues = blocking_requirement_issues(
        [
            {
                "id": 41,
                "blocking_mode": "blocking",
                "run_id": 9,
                "verdict": "undetermined",
                "verdict_reason": "The capture omits the checkout confirmation.",
                "completed_at": "2026-08-20T00:00:00Z",
                "case_outcome": "needs_review",
                "method_id": "browser-inspection",
                "requirement_source": "explicit",
            }
        ],
        accepted_shas=(),
        public_ref="YOK-41",
        require_any=True,
    )

    assert len(issues) == 1
    assert issues[0].state == "incomplete"
    assert "checkout confirmation" in issues[0].detail
