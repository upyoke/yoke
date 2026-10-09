"""Collective delivery closes each member through its pinned workflow gates."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.strategy_execution_test_support import seed_strategy_doc
from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _parked_owner,
    _project,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _landing_evidence,
    _no_obligation,
)
from runtime.api.domain.test_run_success_member_settlement import (
    _claim_held,
    _executing_run,
    _run,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.backlog import (
    insert_epic_task,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.strategy_execution import link_execution_document


def _member(conn, *, item_id: int, workflow: str, complete: bool = True) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id=workflow,
        status="release",
        deployment_flow=COMPLETION_FLOW,
        merged_at=iso8601_now(),
    )
    _parked_owner(conn, f"holder-{item_id}", item_id)
    _no_obligation(conn, item_id, reason="no observable runtime change")
    if workflow == "dash":
        _landing_evidence(conn, item_id)
    else:
        head_sha = "a" * 40
        record_entry(
            conn,
            item_id=item_id,
            branch=f"lane-{item_id}",
            target="main",
            commit_sha=head_sha,
            merge_sha="b" * 40,
        )
        requirement = insert_qa_requirement(
            conn,
            item_id=item_id,
            qa_kind="command",
            qa_phase="verification",
            workflow_transition_id="reviewing-implementation",
        )
        insert_qa_run(
            conn,
            qa_requirement_id=requirement["id"],
            verdict="pass",
            completed_at=iso8601_now(),
            raw_result=json.dumps({"verification_tree": {"head_sha": head_sha}}),
        )
    if workflow == "epic":
        insert_epic_task(conn, epic_id=item_id, task_num=1, status="done")
    if workflow == "blitz":
        slug = "EXECUTION-PLAN"
        content = "# Plan\n"
        if complete:
            content += (
                "\n## Completion\n"
                "- Completed: the document's work\n"
                "- Changed: delivery behavior\n"
                "- Remaining: nothing\n"
                "- Verification identities: passing candidate checks\n"
                "- Parent reconciliation: parent plan updated\n"
            )
        seed_strategy_doc(conn, slug, content)
        link_execution_document(
            conn,
            item_id=item_id,
            project_id=1,
            slug=slug,
            actor_id=2,
            session_id=f"holder-{item_id}",
        )


def test_mixed_workflows_close_together_without_direct_evidence(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    members = tuple(range(9881, 9885))
    for item_id, workflow in zip(
        members, ("blitz", "issue", "epic", "dash"), strict=True
    ):
        _member(test_db, item_id=item_id, workflow=workflow)
    _executing_run(test_db, "run-mixed-workflows", members)

    refusal = cmd_update("run-mixed-workflows", "status", "succeeded")
    assert refusal is None, refusal

    assert _run(test_db, "run-mixed-workflows") == ("succeeded", True)
    for item_id in members:
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)
    evidence = test_db.execute(
        "SELECT item_id FROM item_gate_satisfactions WHERE obligation='delivery_evidence' "
        "AND item_id=ANY(%s)",
        (list(members),),
    ).fetchall()
    assert sorted(row["item_id"] for row in evidence) == list(members)


def test_incomplete_blitz_document_holds_collective_settlement(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    item_id = 9886
    _member(test_db, item_id=item_id, workflow="blitz", complete=False)
    _executing_run(test_db, "run-incomplete-document", (item_id,))

    refusal = cmd_update("run-incomplete-document", "status", "succeeded")

    assert refusal and "execution document is not ready to close" in refusal, refusal
    assert _run(test_db, "run-incomplete-document") == ("executing", True)
    assert _status(test_db, item_id) == "release"
    assert _claim_held(test_db, item_id)


@pytest.mark.parametrize("workflow", ("issue", "epic"))
def test_non_direct_workflow_keeps_its_done_qa_gate(test_db, monkeypatch, workflow):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    item_id = 9887
    _member(test_db, item_id=item_id, workflow=workflow)
    insert_qa_requirement(
        test_db,
        item_id=item_id,
        qa_kind="command",
        qa_phase="verification",
        blocking_mode="blocking",
        instructions="required check",
    )
    _executing_run(test_db, "run-unpassed-verification", (item_id,))

    refusal = cmd_update("run-unpassed-verification", "status", "succeeded")

    assert refusal
    assert _status(test_db, item_id) == "release"
    assert _claim_held(test_db, item_id)
