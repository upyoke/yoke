"""Terminal proof follows the actual code, host or endpoint subject."""

import json

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.session_holdings import insert_lease, insert_session
from yoke_core.domain.qa_terminal_records import _blocking_requirement_rows
from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues
from yoke_core.domain.qa_subject_proof import proof_subject

STAMP = "2026-10-01T00:00:00Z"
TARGET = "frozen-target"
URL = "https://review.example.test"


def _issues(conn, item):
    return blocking_requirement_issues(
        _blocking_requirement_rows(conn, item["id"]),
        accepted_shas=("a" * 40,),
        public_ref="example",
        require_any=True,
    )


def _machine(conn, *, broken=None, runner="host_control"):
    item = insert_item(conn, status="release")
    config = {"checks": ["installed-contract"]}
    requirement = insert_qa_requirement(
        conn,
        item_id=item["id"],
        method_id="machine-state-check",
        runner_id=runner,
        method_config=json.dumps(config),
        workflow_transition_id="reviewing-implementation",
        host_baseline="installed",
        execution_target_digest=TARGET,
    )
    insert_session(conn, "capture-owner")
    insert_lease(
        conn,
        session_id="capture-owner",
        lease_key="QA_HOST:proof-host",
        released_at=STAMP,
    )
    lease_id = conn.execute(
        "SELECT id FROM work_claims WHERE session_id='capture-owner'"
    ).fetchone()[0]
    receipt = {"lease_id": lease_id, "contract_digest": "issued-contract"}
    raw = {
        "evidence": {
            "host_control_submission": receipt,
            "machine": "proof-host",
            "baseline": "installed",
        },
        "method_config": config,
        "execution_target_digest": TARGET,
    }
    if runner == "agent_mission":
        raw["host_control_submission"] = raw.pop("evidence")["host_control_submission"]
    if broken == "receipt":
        receipt.pop("contract_digest")
    run = insert_qa_run(
        conn,
        qa_requirement_id=requirement["id"],
        performed_by=runner,
        raw_result=json.dumps(raw),
        started_at=STAMP,
        completed_at=STAMP,
        verdict="pass",
    )
    case = {
        "requirement_id": requirement["id"],
        "runner_id": runner,
        "host_baseline": "other" if broken == "baseline" else "installed",
        "method_config": config,
    }
    result = {"run_id": run["id"] + 1 if broken == "run" else run["id"]}
    conn.execute(
        "INSERT INTO qa_plan_executions(id,item_id,transition_id,session_id,roster_digest,"
        "roster_json,state,created_at,heartbeat_at,execution_target_digest) "
        "VALUES('observed-machine',%s,'reviewing-implementation',%s,'roster',%s,'completed',%s,%s,%s)",
        (
            item["id"],
            "unrelated-owner" if broken == "session" else "capture-owner",
            json.dumps([case]),
            STAMP,
            STAMP,
            "other-target" if broken == "target" else TARGET,
        ),
    )
    conn.execute(
        "INSERT INTO qa_plan_execution_results(execution_id,ordinal,requirement_id,result_json,completed_at) "
        "VALUES('observed-machine',0,%s,%s,%s)",
        (requirement["id"], json.dumps(result), STAMP),
    )
    conn.commit()
    return item, requirement, run


@pytest.mark.parametrize("runner", ["host_control", "agent_mission"])
def test_machine_proof_settles_without_repository_sha(test_db, runner):
    item, _, run = _machine(test_db, runner=runner)
    assert _issues(test_db, item) == []
    assert "verification_tree" not in json.loads(run["raw_result"])


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


def test_code_subject_retains_exact_observed_revision_requirement(test_db):
    item = insert_item(test_db, status="release")
    requirement = insert_qa_requirement(test_db, item_id=item["id"], runner_id="ci_run")
    insert_qa_run(
        test_db, qa_requirement_id=requirement["id"], verdict="pass", raw_result="{}"
    )
    [issue] = _issues(test_db, item)
    assert issue.state == "stale-sha"
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
