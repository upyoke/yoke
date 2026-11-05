"""Terminal proof follows the actual code, host or endpoint subject."""

from runtime.api.domain.qa_subject_proof_test_support import (
    STAMP as STAMP,
    TARGET as TARGET,
    _machine as _machine,
)


import json

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.qa_terminal_records import _blocking_requirement_rows
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues
from yoke_core.domain.qa_subject_proof import proof_subject

URL = "https://review.example.test"


def _issues(conn, item):
    return blocking_requirement_issues(
        _blocking_requirement_rows(conn, item["id"]),

        public_ref="example",
        require_any=True,
    )


@pytest.mark.parametrize("runner", ["host_control", "agent_mission"])
def test_machine_proof_settles_with_start_commit(test_db, runner):
    item, _, run = _machine(test_db, runner=runner)
    assert _issues(test_db, item) == []
    assert json.loads(run["raw_result"])["verification_tree"]["head_sha"] == "a" * 40


@pytest.mark.parametrize("broken", ["receipt", "run", "session", "baseline", "target"])
def test_unrelated_or_missing_machine_proof_cannot_be_rescued_by_a_lane(
    test_db, broken
):
    item, _, _ = _machine(test_db, broken=broken)
    [issue] = _issues(test_db, item)
    assert issue.state == "subject-unproven"
    assert issue.detail.startswith("qa_machine_")


def test_new_machine_attempt_cannot_borrow_previous_admission(test_db):
    item, requirement, prior = _machine(test_db)
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="host_control",
        started_at="2026-10-02T00:00:00Z",
        raw_result=prior["raw_result"],
        verdict="pass",
    )
    [issue] = _issues(test_db, item)
    assert issue.state == "subject-unproven"
    assert "exact capture" in issue.detail


@pytest.mark.parametrize("observed", [URL, "https://wrong.example.test", ""])
def test_endpoint_command_proves_its_observed_target(test_db, observed):
    item = insert_item(test_db, status="release")
    config = {"command": "check-config", "requires_base_url": True}
    requirement = insert_qa_requirement(
        test_db,
        item_id=item["id"],
        method_id="command",
        runner_id="worktree_run",
        method_config=json.dumps(config),
        execution_target_digest=TARGET,
        execution_target_json=json.dumps({"endpoints": {"app_url": URL}}),
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="worktree_run",
        verdict="pass",
        raw_result=json.dumps(
            {
                "verification_tree": {"head_sha": "a" * 40},
                "method_config": config,
                "execution_target_digest": TARGET,
                "base_url": observed,
            }
        ),
    )
    issues = _issues(test_db, item)
    assert [issue.state for issue in issues] == (
        [] if observed == URL else ["subject-unproven"]
    )


def test_code_subject_needs_no_commit_observation(test_db):
    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(test_db, item_id=item["id"], runner_id="ci_run")
    insert_qa_run(
        test_db, qa_requirement_id=requirement["id"], verdict="pass", raw_result="{}"
    )
    assert _issues(test_db, item) == []
    assert (
        proof_subject(
            {
                "runner_id": "browser_substrate",
                "method_config": {"requires_base_url": True},
            }
        )
        == "code"
    )


def test_terminal_pass_requires_its_own_current_configuration(test_db):
    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(
        test_db,
        item_id=item["id"],
        runner_id="ci_run",
        method_config='{"command":"new"}',
    )
    insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        verdict="pass",
        raw_result=json.dumps(
            {
                "method_config": {"command": "old"},
                "verification_tree": {"head_sha": "a" * 40},
            }
        ),
    )
    [issue] = _issues(test_db, item)
    assert issue.state == "stale-proof"


def test_direct_machine_case_uses_its_own_canonical_artifact(test_db):
    item, requirement, run = _machine(test_db)
    test_db.execute(
        "DELETE FROM qa_plan_execution_results WHERE requirement_id=%s",
        (requirement["id"],),
    )
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,created_at) VALUES(%s,'machine_evidence',%s)",
        (run["id"], STAMP),
    )
    test_db.commit()
    assert _issues(test_db, item) == []
