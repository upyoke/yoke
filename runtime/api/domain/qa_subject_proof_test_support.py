# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
            "test_machine": "proof-host",
            "baseline": "installed",
        },
        "verification_tree": {"head_sha": "a" * 40},
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
        "verification_tree": {"head_sha": "a" * 40},
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
