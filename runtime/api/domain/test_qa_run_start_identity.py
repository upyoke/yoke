"""Every runner records its start commit, independent of later lane movement."""

import json

import pytest

from runtime.api.fixtures.backlog import (
    insert_item,
    insert_item_worktree,
    insert_qa_requirement,
)
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_run_verdict_record import insert_qa_run, update_qa_run
from yoke_core.domain.qa_terminal_records import _blocking_requirement_rows
from yoke_core.domain.item_detail_qa import qa_rows

START = "a" * 40
LATER = "b" * 40
STAMP = "2026-10-01T00:00:00Z"


@pytest.mark.parametrize(
    "runner",
    [
        "agent_mission",
        "host_control",
        "ci_run",
        "worktree_run",
        "browser_substrate",
        "agent",
        "human",
    ],
)
def test_run_start_identity_survives_new_evidence_and_lane_advance(test_db, runner):
    item = insert_item(test_db)
    lane = insert_item_worktree(
        test_db, item_id=item["id"], branch="lane", path="/lane"
    )
    test_db.execute(
        "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s", (START, lane["id"])
    )
    requirement = insert_qa_requirement(test_db, item_id=item["id"], runner_id=runner)
    run = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by=runner,
        qa_kind="smoke",
        started_at=STAMP,
        created_at=STAMP,
        raw_result='{"capture":"started"}',
    )
    raw = test_db.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run.run_id,)
    ).fetchone()[0]
    assert recorded_head_sha(raw) == START
    test_db.execute(
        "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s", (LATER, lane["id"])
    )
    update_qa_run(
        test_db,
        run.run_id,
        {
            "raw_result": json.dumps(
                {"evidence": "finished", "verification_tree": {"head_sha": LATER}}
            )
        },
    )
    raw = test_db.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run.run_id,)
    ).fetchone()[0]
    assert recorded_head_sha(raw) == LATER
    assert json.loads(raw)["evidence"] == "finished"


def test_merge_and_terminal_use_identical_machine_proof(test_db):
    from runtime.api.domain.test_qa_subject_proof import _machine

    item, requirement, _ = _machine(test_db, runner="agent_mission")
    terminal = {
        row["id"]: row for row in _blocking_requirement_rows(test_db, item["id"])
    }
    merge = {row["id"]: row for row in qa_rows(test_db, item["id"], include_proof=True)}
    for field in (
        "run_id",
        "recorded_head_sha",
        "current_passing_proof",
        "subject_proof_error",
        "human_review",
    ):
        assert merge[requirement["id"]][field] == terminal[requirement["id"]][field]
    assert merge[requirement["id"]]["subject_proof_error"] == ""


def test_start_commit_does_not_replace_served_build_observation(test_db):
    item = insert_item(test_db)
    lane = insert_item_worktree(
        test_db, item_id=item["id"], branch="lane", path="/lane"
    )
    test_db.execute(
        "UPDATE item_worktrees SET commit_sha=%s WHERE id=%s", (START, lane["id"])
    )
    requirement = insert_qa_requirement(test_db, item_id=item["id"])
    run = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="browser_substrate",
        qa_kind="smoke",
        started_at=STAMP,
        created_at=STAMP,
        raw_result=json.dumps({"code_identity": {"sha": LATER}}),
    )
    raw = test_db.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run.run_id,)
    ).fetchone()[0]
    assert recorded_head_sha(raw) == LATER
    assert "verification_tree" not in json.loads(raw)
    assert json.loads(raw)["code_identity"]["sha"] == LATER




def test_start_observation_is_retained_when_finished_evidence_has_no_commit():
    from yoke_core.domain.qa_run_start_identity import retain_start_commit
    from yoke_core.domain.qa_run_commit_binding import wrap_evidence

    raw = retain_start_commit(wrap_evidence("started", START), '{"evidence":"finished"}')
    assert recorded_head_sha(raw) == START
    assert json.loads(raw)["evidence"] == "finished"
