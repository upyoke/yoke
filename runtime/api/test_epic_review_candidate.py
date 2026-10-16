"""Real task review writes bind the worker candidate and preserve refusals."""

# ruff: noqa: F811

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_item
from runtime.api.domain.handlers._epic_task_review_state_test_helpers import (
    make_request,
)
from runtime.api.test_epic_review_environment import review_db  # noqa: F401
from yoke_core.domain.handlers import workflow_item_epic_task_review as handlers
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim

SHA = "a" * 40
OTHER = "b" * 40


@pytest.fixture
def task_review(review_db, tmp_path):
    lane = str(tmp_path / "remote-worker")
    review_db.execute(
        "INSERT INTO item_worktrees "
        "(id,item_id,branch,path,commit_sha,lane_role,state,created_at,updated_at) "
        "VALUES (10,42,'worker',%s,%s,'worker','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (lane, SHA),
    )
    review_db.execute("UPDATE epic_tasks SET item_worktree_id=10 WHERE epic_id=42")
    review_db.commit()
    result = handlers.handle_review_seed(
        make_request("workflow_item.epic_task.review_seed")
    )
    assert result.primary_success, result.error
    return review_db, lane


def _insert(verdict="pass", head_sha=SHA):
    payload = {"verdict": verdict, "body": "Complete independent review evidence"}
    if head_sha is not None:
        payload["head_sha"] = head_sha
    return handlers.handle_review_insert(
        make_request("workflow_item.epic_task.review_insert", payload=payload)
    )


def _runs(conn):
    return conn.execute("SELECT * FROM qa_runs ORDER BY id").fetchall()


def test_real_pass_binds_task_worker_and_retains_report(task_review):
    conn, lane = task_review
    # The newest parent/integration lane must not become the review's subject.
    conn.execute(
        "INSERT INTO item_worktrees "
        "(id,item_id,branch,path,commit_sha,lane_role,state,created_at,updated_at) "
        "VALUES (11,42,'integration','/remote/integration',%s,'integration','active',"
        "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (OTHER,),
    )
    conn.commit()
    result = _insert()
    assert result.primary_success, result.error
    (run,) = _runs(conn)
    assert run["verdict"] == "pass"
    raw = json.loads(run["raw_result"])
    assert raw["body"] == "Complete independent review evidence"
    assert raw["verification_tree"] == {"head_sha": SHA, "root": lane}
    review = handlers.handle_review_get(
        make_request("workflow_item.epic_task.review_get")
    )
    assert review.primary_success
    assert (
        "|PASS|Complete independent review evidence|" in review.result_payload["review"]
    )


def test_real_fail_persists_before_retry_without_pass_candidate(task_review):
    conn, _ = task_review
    result = _insert("fail", None)
    assert result.primary_success, result.error
    (run,) = _runs(conn)
    assert run["verdict"] == "fail"
    assert "verification_tree" not in json.loads(run["raw_result"])
    assert (
        conn.execute("SELECT status FROM epic_tasks WHERE epic_id=42").fetchone()[0]
        == "planning"
    )


@pytest.mark.parametrize(
    "head,reason", [(None, "candidate_required"), (OTHER, "candidate_mismatch")]
)
def test_missing_or_wrong_candidate_keeps_real_creator_refusal(
    task_review, head, reason
):
    conn, _ = task_review
    result = _insert(head_sha=head)
    assert not result.primary_success
    assert result.error.code == "downstream_failure"
    assert "implementation_review_run_create_failed" in result.error.message
    assert "task_review_" + reason in result.error.message
    assert "--head-sha" in result.error.message
    assert "Inspect review-get" in result.error.message
    assert _runs(conn) == []


@pytest.mark.parametrize("defect", ["foreign", "integration", "released"])
def test_unowned_or_wrong_role_or_released_lane_cannot_supply_candidate(
    task_review, defect
):
    conn, _ = task_review
    if defect == "foreign":
        insert_item(conn, id=43, title="Another epic", workflow_id="epic")
        conn.execute("UPDATE item_worktrees SET item_id=43 WHERE id=10")
    elif defect == "integration":
        conn.execute("UPDATE item_worktrees SET lane_role='integration' WHERE id=10")
    else:
        conn.execute("UPDATE item_worktrees SET state='released' WHERE id=10")
    conn.commit()
    result = _insert()
    assert not result.primary_success
    assert "task_review_lane_invalid" in result.error.message
    assert _runs(conn) == []


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize("defect", ["clean", "dirty", "head", "branch"])
def test_local_worker_checkout_must_match_reviewed_candidate(
    task_review, tmp_path, defect
):
    conn, _ = task_review
    root = tmp_path / "worker"
    root.mkdir()
    _git(root, "init", "-b", "worker")
    _git(
        root,
        "-c",
        "user.name=Reviewer",
        "-c",
        "user.email=review@example.test",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "--allow-empty",
        "-m",
        "Candidate",
    )
    head = _git(root, "rev-parse", "HEAD")
    conn.execute(
        "UPDATE item_worktrees SET path=%s,commit_sha=%s WHERE id=10", (str(root), head)
    )
    conn.commit()
    if defect == "dirty":
        (root / "unreviewed.txt").write_text("Unreviewed change")
    elif defect == "head":
        _git(
            root,
            "-c",
            "user.name=Reviewer",
            "-c",
            "user.email=review@example.test",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--allow-empty",
            "-m",
            "Changed candidate",
        )
    elif defect == "branch":
        _git(root, "branch", "-m", "another-worker")
    result = _insert(head_sha=head)
    if defect == "clean":
        assert result.primary_success, result.error
        assert (
            json.loads(_runs(conn)[0]["raw_result"])["verification_tree"]["head_sha"]
            == head
        )
    else:
        assert not result.primary_success
        assert "task_review_" in result.error.message
        assert _runs(conn) == []


def test_registered_epic_claim_gate_rejects_another_holder(task_review):
    conn, _ = task_review
    registration = next(
        row
        for row in handlers.REGISTRATIONS
        if row["function_id"].endswith("review_insert")
    )
    entry = SimpleNamespace(
        function_id=registration["function_id"],
        version="v1",
        claim_required_kind=registration["claim_required_kind"],
    )
    request = make_request(
        entry.function_id,
        payload={"verdict": "pass", "body": "Review", "head_sha": SHA},
    )
    with patch(
        "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
        return_value={"session_id": "different-holder"},
    ):
        refused = verify_claim(entry, request)
    assert refused is not None
    assert refused.error.code == "claim_required"
    assert _runs(conn) == []
