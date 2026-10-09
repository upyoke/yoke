"""Snapshot tightening must retain protected proof of an unchanged landing."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run


def _landed_receipt(conn, *, raw_patch=None, config_patch=None, performer="ci_run"):
    item_id = 9231
    head = "a" * 40
    insert_item(conn, id=item_id, workflow_id="dash", status="release")
    config = {"ci_workflow": "ci.yml", "command": "run-tests", **(config_patch or {})}
    requirement = insert_qa_requirement(
        conn,
        item_id=item_id,
        method_id="command-ci",
        runner_id="ci_run",
        method_config=json.dumps(config),
        execution_target_digest="frozen-target",
    )
    raw = {
        "verification_tree": {"head_sha": head},
        "merge_queue_batch": {"combined_head_sha": head, "merge_sha": head},
        **(raw_patch or {}),
    }
    run = insert_qa_run(
        conn,
        qa_requirement_id=requirement["id"],
        performed_by=performer,
        raw_result=json.dumps(raw),
    )
    record_entry(
        conn,
        item_id=item_id,
        branch="candidate",
        target="main",
        commit_sha=head,
        merge_sha=head,
    )
    conn.commit()
    return item_id, int(requirement["id"]), run


def test_unstamped_protected_receipt_remains_current_for_unchanged_landing(test_db):
    _, requirement_id, run = _landed_receipt(test_db)
    assert has_current_passing_run(test_db, requirement_id)
    assert (
        test_db.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s", (run["id"],)
        ).fetchone()[0]
        == run["raw_result"]
    )


def test_changed_landing_does_not_credit_old_protected_receipt(test_db):
    item_id, requirement_id, _ = _landed_receipt(test_db)
    record_entry(
        test_db,
        item_id=item_id,
        branch="candidate",
        target="main",
        commit_sha="b" * 40,
        merge_sha="c" * 40,
    )
    test_db.commit()
    assert not has_current_passing_run(test_db, requirement_id)


@pytest.mark.parametrize(
    "mutation", ["config", "target", "rebound", "failed", "pending"]
)
def test_corrections_and_latest_nonpassing_attempt_still_hold(test_db, mutation):
    _, requirement_id, _ = _landed_receipt(test_db)
    if mutation == "config":
        test_db.execute(
            "UPDATE qa_requirements SET method_config=%s WHERE id=%s",
            (json.dumps({"ci_workflow": "ci.yml", "_corrected": True}), requirement_id),
        )
    elif mutation == "target":
        test_db.execute(
            "UPDATE qa_requirements SET target_env='stage' WHERE id=%s",
            (requirement_id,),
        )
    elif mutation == "rebound":
        test_db.execute(
            "UPDATE qa_requirements SET rebound_at=%s WHERE id=%s",
            ("2026-10-09T00:00:00Z", requirement_id),
        )
    else:
        insert_qa_run(
            test_db,
            qa_requirement_id=requirement_id,
            verdict="fail" if mutation == "failed" else None,
        )
    test_db.commit()
    assert not has_current_passing_run(test_db, requirement_id)


@pytest.mark.parametrize(
    "raw_patch,performer",
    [
        ({"merge_queue_batch": {}}, "ci_run"),
        ({"method_config": {"command": "different"}}, "ci_run"),
        ({"execution_target_digest": "different"}, "ci_run"),
        ({}, "worktree_run"),
    ],
)
def test_missing_batch_or_conflicting_snapshots_never_gain_credit(
    test_db, raw_patch, performer
):
    _, requirement_id, _ = _landed_receipt(
        test_db, raw_patch=raw_patch, performer=performer
    )
    assert not has_current_passing_run(test_db, requirement_id)
