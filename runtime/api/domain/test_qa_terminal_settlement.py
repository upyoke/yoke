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
    review = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="agent",
        verdict="pass",
        raw_result="{}",
    )
    test_db.execute(
        "INSERT INTO qa_plan_executions(id,item_id,session_id,roster_digest,roster_json,"
        "state,created_at,heartbeat_at) VALUES(%s,%s,'review-owner','digest','[]',"
        "'completed',%s,%s)",
        (
            "historical-execution",
            item["id"],
            "2026-01-01T00:00:02Z",
            "2026-01-01T00:00:02Z",
        ),
    )
    test_db.execute(
        "INSERT INTO qa_plan_review_bundles(id,execution_id,roster_digest,state,bundle_digest,"
        "bundle_json,created_at) VALUES(%s,%s,'digest','completed',%s,'{}',%s)",
        ("historical-review", "historical-execution", "digest", "2026-01-01T00:00:02Z"),
    )
    test_db.execute(
        "INSERT INTO qa_plan_review_verdicts(bundle_id,requirement_id,capture_run_id,"
        "review_run_id,verdict,rationale,created_at) VALUES(%s,%s,%s,%s,'pass','Observed',%s)",
        (
            "historical-review",
            requirement["id"],
            capture["id"],
            review["id"],
            "2026-01-01T00:00:02Z",
        ),
    )
    test_db.commit()
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


def test_new_attempt_does_not_release_older_attempts_live_host(test_db):
    from runtime.api.fixtures.session_holdings import insert_lease
    from yoke_core.domain.qa_terminal_records import live_qa_leases

    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    insert_lease(test_db, session_id="qa-owner", lease_key="QA_HOST:terminal-host")
    lease_id = test_db.execute(
        "SELECT id FROM work_claims WHERE session_id='qa-owner'"
    ).fetchone()[0]
    old = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict=None,
        raw_result=json.dumps(
            {
                "evidence": {
                    "host_control_submission": {
                        "lease_id": lease_id,
                        "contract_digest": "submitted-contract",
                    }
                }
            }
        ),
    )
    insert_qa_run(test_db, qa_requirement_id=requirement["id"], verdict="pass")
    assert live_qa_leases(test_db, item["id"]) == [(lease_id, f"attempt {old['id']}")]
    records = find_unsettled_records(test_db, item_id=item["id"])
    assert [(r.kind, r.record_id) for r in records] == [("host lease", str(lease_id))]
    test_db.execute(
        "UPDATE work_claims SET released_at=%s,release_reason='completed' WHERE id=%s",
        ("2026-10-01T00:00:01Z", lease_id),
    )
    test_db.commit()
    assert find_unsettled_records(test_db, item_id=item["id"]) == []
